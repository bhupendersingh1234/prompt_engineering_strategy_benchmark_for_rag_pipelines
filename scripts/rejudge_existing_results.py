"""
One-off helper: re-runs the hallucination judge on results already produced
by src/run_benchmark.py, without re-running generation. Use this after
changing the judge prompt/schema in src/evaluate.py (e.g. the claim-
decomposition fix) so existing answers get re-graded without re-paying for
the OpenAI generation calls.

Reads results/raw_outputs/<strategy>.jsonl, overwrites the judge_* columns
in place, and rewrites results/summary.csv / summary.json with the updated
accuracy / hallucination_rate.

Usage:
    python scripts/rejudge_existing_results.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from tqdm import tqdm

import config
from src.evaluate import get_judge_llm, judge_answer, save_json


def main():
    summary_path = config.RESULTS_DIR / "summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"{summary_path} not found -- run src.run_benchmark first.")
    summary_df = pd.read_csv(summary_path, index_col="strategy")
    judge_llm = get_judge_llm()

    for strategy in config.STRATEGIES:
        if strategy not in summary_df.index:
            print(f"Skipping '{strategy}' (not in summary.csv).")
            continue

        path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        print(f"\n=== {strategy}: re-judging {len(records)} answers ===")
        for r in tqdm(records, desc=f"[{strategy}]"):
            if r.get("error"):
                continue
            judgement = judge_answer(
                judge_llm,
                context=r["retrieved_context"],
                question=r["query"],
                answer=r["answer"],
                reference_answer=r.get("reference_answer") or "",
            )
            r["judge_label"] = judgement.label
            r["judge_is_hallucinated"] = judgement.is_hallucinated
            r["judge_is_correct"] = judgement.is_correct
            r["judge_rationale"] = judgement.rationale
            r.pop("judge_error", None)

        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        df = pd.DataFrame(records)
        ok = df[df["error"].isna()] if "error" in df else df
        summary_df.loc[strategy, "accuracy"] = float(ok["judge_is_correct"].mean())
        summary_df.loc[strategy, "hallucination_rate"] = float(ok["judge_is_hallucinated"].mean())
        print(f"  accuracy={summary_df.loc[strategy, 'accuracy']:.3f}  "
              f"hallucination_rate={summary_df.loc[strategy, 'hallucination_rate']:.3f}")

    summary_df.to_csv(summary_path)
    save_json(summary_df.reset_index().to_dict(orient="records"), config.RESULTS_DIR / "summary.json")
    print(f"\nUpdated {summary_path}")
    print(summary_df)


if __name__ == "__main__":
    main()
