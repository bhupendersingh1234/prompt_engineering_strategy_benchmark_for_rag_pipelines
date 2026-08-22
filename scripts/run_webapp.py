"""
Launches the local web GUI (FastAPI + WebSocket backend, plain-JS frontend)
for the RAG prompt-strategy benchmark. Open http://127.0.0.1:8000/ after
running this.

Usage:
    python scripts/run_webapp.py
    python scripts/run_webapp.py --port 8080
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"Open http://{args.host}:{args.port}/ in your browser.")
    uvicorn.run("webapp.backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
