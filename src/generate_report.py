"""
Turns results/summary.csv (produced by src/run_benchmark.py) into the
comparison charts for the report: accuracy, hallucination rate,
faithfulness, latency, and cost across the 4 prompting strategies, plus a
grouped accuracy-vs-hallucination-rate view and a radar chart.

Usage:
    python -m src.generate_report
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config

STRATEGY_LABELS = {
    "zero_shot": "Zero-shot",
    "few_shot": "Few-shot",
    "chain_of_thought": "Chain-of-Thought",
    "structured_output": "Structured Output",
}
COLORS = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]


def _bar_chart(df, column, title, ylabel, filename, as_percent=False, fmt="{:.2f}"):
    fig, ax = plt.subplots(figsize=(7, 5))
    labels = [STRATEGY_LABELS.get(s, s) for s in df.index]
    values = df[column].fillna(0).values
    plotted = values * 100 if as_percent else values
    bars = ax.bar(labels, plotted, color=COLORS[: len(labels)])
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, v in zip(bars, values):
        text = f"{v*100:.1f}%" if as_percent else fmt.format(v)
        ax.annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    out_path = config.CHARTS_DIR / filename
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


def _grouped_accuracy_hallucination(df, filename="accuracy_vs_hallucination.png"):
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = [STRATEGY_LABELS.get(s, s) for s in df.index]
    x = np.arange(len(labels))
    width = 0.35
    acc = df["accuracy"].fillna(0).values * 100
    hall = df["hallucination_rate"].fillna(0).values * 100
    ax.bar(x - width / 2, acc, width, label="Accuracy", color="#4C72B0")
    ax.bar(x + width / 2, hall, width, label="Hallucination Rate", color="#C44E52")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("%")
    ax.set_title("Accuracy vs. Hallucination Rate by Prompting Strategy",
                 fontsize=13, fontweight="bold")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out_path = config.CHARTS_DIR / filename
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


def _radar_chart(df, filename="radar_comparison.png"):
    metrics = ["accuracy", "ragas_faithfulness", "ragas_answer_relevancy"]
    metrics = [m for m in metrics if m in df.columns]
    inverted_metrics = {"hallucination_rate"}
    if "hallucination_rate" in df.columns:
        metrics.append("hallucination_rate")
    if len(metrics) < 3:
        print("Not enough metrics for a radar chart, skipping.")
        return

    labels = metrics
    n = len(labels)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    for i, strategy in enumerate(df.index):
        values = []
        for m in metrics:
            v = df.loc[strategy, m]
            v = 0.0 if pd.isna(v) else v
            if m in inverted_metrics:
                v = 1.0 - v  # invert so "outward" always means "better"
            values.append(v)
        values += values[:1]
        ax.plot(angles, values, label=STRATEGY_LABELS.get(strategy, strategy),
                color=COLORS[i % len(COLORS)])
        ax.fill(angles, values, color=COLORS[i % len(COLORS)], alpha=0.08)

    display_labels = [
        "1 - hallucination_rate" if m == "hallucination_rate" else m for m in labels
    ]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(display_labels, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_title("Strategy Comparison (outward = better)", fontsize=13, fontweight="bold", y=1.08)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), frameon=False, fontsize=9)
    fig.tight_layout()
    out_path = config.CHARTS_DIR / filename
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


def main():
    summary_path = config.RESULTS_DIR / "summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"{summary_path} not found. Run `python -m src.run_benchmark` first."
        )
    df = pd.read_csv(summary_path, index_col="strategy")
    df = df.reindex([s for s in config.STRATEGIES if s in df.index])

    if "accuracy" in df:
        _bar_chart(df, "accuracy", "Accuracy by Prompting Strategy", "Accuracy",
                   "accuracy.png", as_percent=True)
    if "hallucination_rate" in df:
        _bar_chart(df, "hallucination_rate", "Hallucination Rate by Prompting Strategy",
                   "Hallucination Rate", "hallucination_rate.png", as_percent=True)
    if "ragas_faithfulness" in df:
        _bar_chart(df, "ragas_faithfulness", "RAGAS Faithfulness by Prompting Strategy",
                   "Faithfulness (0-1)", "faithfulness.png")
    if "avg_latency_seconds" in df:
        _bar_chart(df, "avg_latency_seconds", "Average Latency by Prompting Strategy",
                   "Seconds", "latency.png", fmt="{:.2f}s")
    if "avg_cost_usd" in df:
        _bar_chart(df, "avg_cost_usd", "Average Cost per Query by Prompting Strategy",
                   "USD", "cost.png", fmt="${:.5f}")
    if {"accuracy", "hallucination_rate"} <= set(df.columns):
        _grouped_accuracy_hallucination(df)
    _radar_chart(df)


if __name__ == "__main__":
    main()
