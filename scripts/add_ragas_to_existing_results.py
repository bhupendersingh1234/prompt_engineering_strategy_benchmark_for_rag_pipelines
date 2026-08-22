"""
One-off helper: computes RAGAS metrics (Faithfulness, Answer Relevancy) on
results already produced by src/run_benchmark.py, without re-running any
generation or judging -- useful after fixing/enabling RAGAS post-hoc so you
don't have to re-pay for the OpenAI generation + judge calls.

Reads results/raw_outputs/<strategy>.jsonl, writes
results/raw_outputs/<strategy>_ragas.csv, and rewrites results/summary.csv /
summary.json with the ragas_faithfulness / ragas_answer_relevancy columns
merged in.

Usage:
    python scripts/add_ragas_to_existing_results.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from src.evaluate import compute_ragas_metrics, save_json


def load_records(strategy: str) -> list[dict]:
    path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run src.run_benchmark first.")
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    summary_path = config.RESULTS_DIR / "summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"{summary_path} not found -- run src.run_benchmark first.")
    summary_df = pd.read_csv(summary_path, index_col="strategy")

    for strategy in config.STRATEGIES:
        if strategy not in summary_df.index:
            print(f"Skipping '{strategy}' (not in summary.csv).")
            continue

        records = load_records(strategy)
        ok_records = [r for r in records if not r.get("error")]
        print(f"\n=== {strategy}: scoring {len(ok_records)} answers with RAGAS ===")

        ragas_records = [
            {"question": r["query"], "answer": r["answer"], "contexts": [r["retrieved_context"]]}
            for r in ok_records
        ]
        ragas_df = compute_ragas_metrics(ragas_records)
        if ragas_df is None:
            print(f"RAGAS scoring failed for '{strategy}', leaving summary.csv unchanged for it.")
            continue

        ragas_df.to_csv(config.RAW_OUTPUTS_DIR / f"{strategy}_ragas.csv", index=False)
        if "faithfulness" in ragas_df:
            summary_df.loc[strategy, "ragas_faithfulness"] = float(ragas_df["faithfulness"].mean())
        if "answer_relevancy" in ragas_df:
            summary_df.loc[strategy, "ragas_answer_relevancy"] = float(ragas_df["answer_relevancy"].mean())
        print(summary_df.loc[strategy])

    summary_df.to_csv(summary_path)
    save_json(summary_df.reset_index().to_dict(orient="records"), config.RESULTS_DIR / "summary.json")
    print(f"\nUpdated {summary_path}")
    print(summary_df)


if __name__ == "__main__":
    main()
