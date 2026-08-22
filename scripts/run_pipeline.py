"""
Convenience entry point that runs the full pipeline end-to-end:
  1. data_loader  -> pulls RAGTruth QA subset, builds eval + calibration sets
  2. ingest       -> chunks + embeds + indexes the shared corpus into Chroma
  3. run_benchmark -> answers every eval question with all 4 strategies + grades them
  4. generate_report -> renders the comparison charts

Equivalent to running each `python -m src.<module>` step manually (see
README.md) but useful for a single "just run it" command. Requires
OPENAI_API_KEY to be set (steps 2-3 call the OpenAI API).

Usage:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --sample-size 20 --fixture
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import data_loader, ingest, run_benchmark, generate_report  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument("--calibration-size", type=int, default=None)
    parser.add_argument("--fixture", action="store_true",
                         help="Use the bundled offline fixture instead of downloading RAGTruth.")
    parser.add_argument("--skip-ragas", action="store_true")
    parser.add_argument("--skip-calibration", action="store_true")
    args = parser.parse_args()

    import config

    print("### Step 1/4: data_loader ###")
    data_loader.build_dataset(
        sample_size=args.sample_size,
        calibration_size=args.calibration_size,
        use_fixture=args.fixture,
    )

    print("\n### Step 2/4: ingest (chunk + embed + index) ###")
    docs = ingest.load_corpus()
    chunks = ingest.chunk_documents(docs)
    ingest.build_vectorstore(chunks)
    print(f"Indexed {len(chunks)} chunks from {len(docs)} documents.")

    print("\n### Step 3/4: run_benchmark ###")
    sys.argv = ["run_benchmark"]
    if args.skip_ragas:
        sys.argv.append("--skip-ragas")
    if args.skip_calibration:
        sys.argv.append("--skip-calibration")
    run_benchmark.main()

    print("\n### Step 4/4: generate_report ###")
    generate_report.main()

    print(f"\nDone. See {config.RESULTS_DIR} for summary.csv/json and {config.CHARTS_DIR} for charts.")


if __name__ == "__main__":
    main()
