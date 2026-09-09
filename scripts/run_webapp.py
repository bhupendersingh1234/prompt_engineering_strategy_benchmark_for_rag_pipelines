"""
Launches the local web GUI (FastAPI + WebSocket backend, plain-JS frontend)
for the RAG prompt-strategy benchmark. Open http://127.0.0.1:8000/ after
running this.

Usage:
    python scripts/run_webapp.py
    python scripts/run_webapp.py --port 8080

    # Demo / rehearsal mode: every artifact (processed data, vector store,
    # results) is redirected to ./demo_workspace instead of the real
    # data/, chroma_store/, results/ -- so a live "Run pipeline" click
    # during a demo can never overwrite your actual committed results.
    python scripts/run_webapp.py --demo
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--demo", action="store_true",
                         help="Redirect all generated artifacts to ./demo_workspace "
                              "instead of the real data/, chroma_store/, results/.")
    parser.add_argument("--workdir", type=str, default=None,
                         help="Custom workdir name (implies --demo-style isolation). "
                              "Overrides --demo's default of 'demo_workspace'.")
    args = parser.parse_args()

    workdir = args.workdir or ("demo_workspace" if args.demo else None)
    if workdir:
        os.environ["RAG_WORKDIR"] = workdir
        print(f"DEMO MODE: all artifacts isolated under ./{workdir}/ "
              f"-- your real data/results/chroma_store are untouched.")
    else:
        print("REAL MODE: this run reads/writes the actual data/, chroma_store/, "
              "results/ directories -- results/summary.csv already has your "
              "committed benchmark. Use --demo for a rehearsal that can't touch it.")

    import uvicorn  # imported after RAG_WORKDIR is set, so config.py picks it up
    print(f"Open http://{args.host}:{args.port}/ in your browser.")
    uvicorn.run("webapp.backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
