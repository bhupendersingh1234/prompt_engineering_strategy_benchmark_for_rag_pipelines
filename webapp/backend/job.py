"""
Runs the full pipeline (data_loader -> ingest -> calibration -> 4 strategies
-> report) in a background thread, emitting a live event for every
meaningful step. This is the same code path as scripts/run_pipeline.py /
src/run_benchmark.py -- webapp/backend does not reimplement pipeline logic,
it just calls the same src/*.py functions and adds an `emit()` callback at
the points those functions already support one (run_one_strategy,
calibrate_judge) or wraps a whole stage (data_loader, ingest, report).

Only one job runs at a time -- this is a single-operator local dev tool, not
a multi-tenant service.
"""
import json
import threading
import time
import traceback

import pandas as pd

import config
from src import data_loader, generate_report, ingest, run_benchmark
from src.evaluate import calibrate_judge, compute_ragas_metrics, get_judge_llm, save_json
from src.rag_chain import get_llm


class JobState:
    def __init__(self):
        self.status = "idle"  # idle | running | done | error
        self.error = None
        self.started_at = None
        self.finished_at = None
        self.request = None

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "request": self.request,
        }


state = JobState()
_lock = threading.Lock()


def start_job(payload: dict, emit) -> bool:
    """Returns False (and starts nothing) if a job is already running."""
    with _lock:
        if state.status == "running":
            return False
        state.status = "running"
        state.error = None
        state.started_at = time.time()
        state.finished_at = None
        state.request = payload

    thread = threading.Thread(target=_run, args=(payload, emit), daemon=True)
    thread.start()
    return True


def _run(payload: dict, emit) -> None:
    try:
        _run_pipeline(payload, emit)
        state.status = "done"
    except Exception as exc:  # noqa: BLE001
        state.status = "error"
        state.error = str(exc)
        emit({"type": "error", "message": str(exc), "traceback": traceback.format_exc()})
    finally:
        state.finished_at = time.time()
        emit({"type": "job_done", "status": state.status})


def _run_pipeline(payload: dict, emit) -> None:
    sample_size = payload.get("sample_size") or config.EVAL_SAMPLE_SIZE
    calibration_size = payload.get("calibration_size") or config.CALIBRATION_SAMPLE_SIZE
    strategies = payload.get("strategies") or list(config.STRATEGIES)
    use_fixture = bool(payload.get("use_fixture"))
    skip_ragas = bool(payload.get("skip_ragas"))
    skip_calibration = bool(payload.get("skip_calibration"))

    emit({"type": "stage", "stage": "data_loader", "status": "start"})
    eval_rows, cal_rows, corpus_docs = data_loader.build_dataset(
        sample_size=sample_size,
        calibration_size=calibration_size,
        use_fixture=use_fixture,
    )
    emit({
        "type": "stage", "stage": "data_loader", "status": "done",
        "detail": {
            "eval_rows": len(eval_rows),
            "calibration_rows": len(cal_rows),
            "corpus_docs": len(corpus_docs),
        },
    })

    emit({"type": "stage", "stage": "ingest", "status": "start"})
    docs = ingest.load_corpus()
    chunks = ingest.chunk_documents(docs)
    ingest.build_vectorstore(chunks)
    emit({
        "type": "stage", "stage": "ingest", "status": "done",
        "detail": {"documents": len(docs), "chunks": len(chunks)},
    })

    retriever = ingest.get_retriever()
    llm = get_llm()
    judge_llm = get_judge_llm()

    if not skip_calibration:
        emit({"type": "stage", "stage": "calibration", "status": "start",
              "detail": {"total": len(cal_rows)}})

        def on_cal_row(i, total, detail):
            emit({"type": "calibration_row", "index": i, "total": total, **detail})

        cal_metrics = calibrate_judge(cal_rows, judge_llm, on_row=on_cal_row)
        save_json(cal_metrics, config.RESULTS_DIR / "judge_calibration.json")
        emit({
            "type": "stage", "stage": "calibration", "status": "done",
            "detail": {k: v for k, v in cal_metrics.items() if k != "details"},
        })

    summary_rows = []
    for strategy in strategies:
        emit({"type": "stage", "stage": f"strategy:{strategy}", "status": "start",
              "detail": {"total": len(eval_rows)}})

        def on_row(i, total, record, strategy=strategy):
            emit({
                "type": "row",
                "strategy": strategy,
                "index": i,
                "total": total,
                "query": record["query"],
                "answer": (record["answer"] or "")[:280],
                "judge_label": record.get("judge_label"),
                "judge_is_hallucinated": record.get("judge_is_hallucinated"),
                "judge_is_correct": record.get("judge_is_correct"),
                "latency_seconds": record["latency_seconds"],
                "total_tokens": record["total_tokens"],
                "error": record.get("error"),
            })

        records = run_benchmark.run_one_strategy(
            strategy, eval_rows, retriever, llm, judge_llm, on_row=on_row
        )

        out_path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        ragas_df = None
        if not skip_ragas:
            emit({"type": "stage", "stage": f"ragas:{strategy}", "status": "start"})
            ragas_records = [
                {"question": r["query"], "answer": r["answer"], "contexts": [r["retrieved_context"]]}
                for r in records if r.get("error") is None
            ]
            ragas_df = compute_ragas_metrics(ragas_records)
            if ragas_df is not None:
                ragas_df.to_csv(config.RAW_OUTPUTS_DIR / f"{strategy}_ragas.csv", index=False)
            emit({"type": "stage", "stage": f"ragas:{strategy}", "status": "done"})

        agg = run_benchmark.aggregate(records, ragas_df)
        agg["strategy"] = strategy
        summary_rows.append(agg)

        emit({"type": "stage", "stage": f"strategy:{strategy}", "status": "done", "detail": agg})
        emit({"type": "strategy_summary", "strategy": strategy, "summary": agg})

    emit({"type": "stage", "stage": "report", "status": "start"})
    summary_df = pd.DataFrame(summary_rows).set_index("strategy")
    summary_df.to_csv(config.RESULTS_DIR / "summary.csv")
    save_json(summary_rows, config.RESULTS_DIR / "summary.json")
    generate_report.main()
    emit({"type": "stage", "stage": "report", "status": "done"})
    emit({"type": "summary", "rows": summary_rows})
