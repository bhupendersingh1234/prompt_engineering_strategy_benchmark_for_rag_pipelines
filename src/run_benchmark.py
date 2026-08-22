"""
Main experiment runner.

For every prompting strategy in config.STRATEGIES, answers every question
in the processed RAGTruth QA eval set (data/processed/ragtruth_qa.jsonl)
using the SAME retriever/LLM/top-k (src/ingest.py, src/rag_chain.py), then
grades each answer with the LLM hallucination judge (src/evaluate.py) and,
optionally, RAGAS. Writes per-strategy raw outputs and an aggregated
comparison table.

Usage:
    python -m src.run_benchmark
    python -m src.run_benchmark --sample-size 20 --strategies zero_shot,few_shot
    python -m src.run_benchmark --skip-ragas --skip-calibration
"""
import argparse
import json
import time

import pandas as pd
from tqdm import tqdm

import config
from src.ingest import get_retriever
from src.rag_chain import get_llm, run_strategy
from src.evaluate import get_judge_llm, judge_answer, calibrate_judge, compute_ragas_metrics, save_json


def load_eval_set(path=None, limit=None):
    path = path or config.PROCESSED_DATASET_PATH
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def load_calibration_set(path=None):
    path = path or config.CALIBRATION_SET_PATH
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_one_strategy(strategy: str, eval_rows: list[dict], retriever, llm, judge_llm,
                      on_row=None) -> list[dict]:
    """on_row(index, total, record), if given, fires after each question is
    answered and judged -- used by webapp/backend to stream live progress
    over a WebSocket. Purely additive: the CLI path (on_row=None) is
    unchanged."""
    records = []
    for i, row in enumerate(tqdm(eval_rows, desc=f"[{strategy}]")):
        result = run_strategy(strategy, row["query"], retriever, llm)

        record = {
            "id": row["id"],
            "strategy": strategy,
            "query": row["query"],
            "reference_answer": row.get("reference_answer"),
            "answer": result.answer,
            "reasoning": result.reasoning,
            "retrieved_context": result.context_text,
            "num_context_docs": len(result.context_docs),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "latency_seconds": result.latency_seconds,
            "estimated_cost_usd": result.estimated_cost_usd,
            "error": result.error,
        }
        if result.structured is not None:
            record["is_grounded_self_reported"] = getattr(result.structured, "is_grounded", None)
            record["confidence_self_reported"] = getattr(result.structured, "confidence", None)
            record["supporting_quotes"] = getattr(result.structured, "supporting_quotes", None)

        if result.error is None:
            try:
                judgement = judge_answer(
                    judge_llm,
                    context=result.context_text,
                    question=row["query"],
                    answer=result.answer,
                    reference_answer=row.get("reference_answer") or "",
                )
                record["judge_label"] = judgement.label
                record["judge_is_hallucinated"] = judgement.is_hallucinated
                record["judge_is_correct"] = judgement.is_correct
                record["judge_rationale"] = judgement.rationale
            except Exception as exc:  # noqa: BLE001
                record["judge_error"] = str(exc)
        records.append(record)
        if on_row is not None:
            on_row(i + 1, len(eval_rows), record)
    return records


def aggregate(records: list[dict], ragas_df: "pd.DataFrame | None") -> dict:
    df = pd.DataFrame(records)
    ok = df[df["error"].isna()] if "error" in df else df

    agg = {
        "n": len(df),
        "n_errors": int(df["error"].notna().sum()) if "error" in df else 0,
        "accuracy": float(ok["judge_is_correct"].mean()) if "judge_is_correct" in ok else None,
        "hallucination_rate": float(ok["judge_is_hallucinated"].mean()) if "judge_is_hallucinated" in ok else None,
        "avg_latency_seconds": float(ok["latency_seconds"].mean()),
        "avg_prompt_tokens": float(ok["prompt_tokens"].mean()),
        "avg_completion_tokens": float(ok["completion_tokens"].mean()),
        "avg_total_tokens": float(ok["total_tokens"].mean()),
        "total_cost_usd": float(ok["estimated_cost_usd"].sum()),
        "avg_cost_usd": float(ok["estimated_cost_usd"].mean()),
    }
    if ragas_df is not None and len(ragas_df) == len(df):
        if "faithfulness" in ragas_df:
            agg["ragas_faithfulness"] = float(ragas_df["faithfulness"].mean())
        if "answer_relevancy" in ragas_df:
            agg["ragas_answer_relevancy"] = float(ragas_df["answer_relevancy"].mean())
    return agg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=None,
                         help="Limit number of eval questions per strategy (default: all in the processed file).")
    parser.add_argument("--strategies", type=str, default=",".join(config.STRATEGIES))
    parser.add_argument("--skip-ragas", action="store_true")
    parser.add_argument("--skip-calibration", action="store_true")
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    eval_rows = load_eval_set(limit=args.sample_size)
    print(f"Loaded {len(eval_rows)} eval questions.")

    retriever = get_retriever()
    llm = get_llm()
    judge_llm = get_judge_llm()

    if not args.skip_calibration:
        cal_rows = load_calibration_set()
        print(f"Calibrating hallucination judge on {len(cal_rows)} RAGTruth-labeled rows ...")
        cal_metrics = calibrate_judge(cal_rows, judge_llm)
        print(f"Judge calibration -> precision={cal_metrics['precision']:.2f} "
              f"recall={cal_metrics['recall']:.2f} f1={cal_metrics['f1']:.2f} "
              f"accuracy={cal_metrics['accuracy']:.2f}")
        save_json(cal_metrics, config.RESULTS_DIR / "judge_calibration.json")

    summary_rows = []
    for strategy in strategies:
        print(f"\n=== Running strategy: {strategy} ===")
        t0 = time.perf_counter()
        records = run_one_strategy(strategy, eval_rows, retriever, llm, judge_llm)
        wall_time = time.perf_counter() - t0

        out_path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Wrote {len(records)} records -> {out_path} (wall time {wall_time:.1f}s)")

        ragas_df = None
        if not args.skip_ragas:
            ragas_records = [
                {"question": r["query"], "answer": r["answer"],
                 "contexts": [r["retrieved_context"]]}
                for r in records if r.get("error") is None
            ]
            ragas_df = compute_ragas_metrics(ragas_records)
            if ragas_df is not None:
                ragas_df.to_csv(config.RAW_OUTPUTS_DIR / f"{strategy}_ragas.csv", index=False)

        agg = aggregate(records, ragas_df)
        agg["strategy"] = strategy
        agg["wall_time_seconds"] = wall_time
        summary_rows.append(agg)
        print({k: v for k, v in agg.items() if k != "strategy"})

    summary_df = pd.DataFrame(summary_rows).set_index("strategy")
    summary_path = config.RESULTS_DIR / "summary.csv"
    summary_df.to_csv(summary_path)
    save_json(summary_rows, config.RESULTS_DIR / "summary.json")
    print(f"\nSaved comparison summary -> {summary_path}")
    print(summary_df)


if __name__ == "__main__":
    main()
