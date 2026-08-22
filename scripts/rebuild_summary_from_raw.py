"""
Recomputes results/summary.csv / summary.json from whatever is currently in
results/raw_outputs/<strategy>.jsonl (+ <strategy>_ragas.csv if present), for
every strategy that has a raw_outputs file. Useful after a partial re-run
(e.g. src.run_benchmark --strategies zero_shot) which only writes a summary
row for the strategies it was given -- this stitches the full comparison
table back together from whatever raw outputs exist on disk, without
re-calling the OpenAI API for strategies that don't need it.

Usage:
    python scripts/rebuild_summary_from_raw.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from src import run_benchmark
from src.evaluate import save_json


def main():
    summary_rows = []
    for strategy in config.STRATEGIES:
        raw_path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
        if not raw_path.exists():
            print(f"Skipping '{strategy}' (no raw_outputs file).")
            continue
        records = []
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        ragas_path = config.RAW_OUTPUTS_DIR / f"{strategy}_ragas.csv"
        ragas_df = pd.read_csv(ragas_path) if ragas_path.exists() else None

        agg = run_benchmark.aggregate(records, ragas_df)
        agg["strategy"] = strategy
        summary_rows.append(agg)
        print(f"{strategy}: n={agg['n']} accuracy={agg.get('accuracy')} "
              f"hallucination_rate={agg.get('hallucination_rate')}")

    summary_df = pd.DataFrame(summary_rows).set_index("strategy")
    summary_df.to_csv(config.RESULTS_DIR / "summary.csv")
    save_json(summary_rows, config.RESULTS_DIR / "summary.json")
    print(f"\nWrote {config.RESULTS_DIR / 'summary.csv'}")
    print(summary_df)


if __name__ == "__main__":
    main()
