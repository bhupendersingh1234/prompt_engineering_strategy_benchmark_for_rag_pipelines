"""
FastAPI app: serves the frontend (webapp/frontend/) and a small JSON+WebSocket
API over the existing pipeline in src/*.py. Run with:

    python scripts/run_webapp.py
    # or
    uvicorn webapp.backend.main:app --reload

Then open http://127.0.0.1:8000/
"""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import config  # noqa: E402
from webapp.backend import job  # noqa: E402
from webapp.backend.events import bus  # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="RAG Prompt Strategy Benchmark", lifespan=lifespan)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class RunRequest(BaseModel):
    sample_size: int | None = None
    calibration_size: int | None = None
    strategies: list[str] | None = None
    use_fixture: bool = False
    skip_ragas: bool = False
    skip_calibration: bool = False


@app.get("/api/config-defaults")
def config_defaults():
    return {
        "strategies": config.STRATEGIES,
        "sample_size": config.EVAL_SAMPLE_SIZE,
        "calibration_size": config.CALIBRATION_SAMPLE_SIZE,
        "top_k": config.TOP_K,
        "llm_model": config.LLM_MODEL,
        "embedding_model": config.EMBEDDING_MODEL,
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
        "has_api_key": bool(config.OPENAI_API_KEY),
    }


@app.get("/api/status")
def status():
    return job.state.snapshot()


@app.post("/api/run")
def run(req: RunRequest):
    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not set in .env")
    started = job.start_job(req.model_dump(), bus.emit)
    if not started:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress.")
    return {"status": "started"}


@app.get("/api/summary")
def summary():
    path = config.RESULTS_DIR / "summary.csv"
    if not path.exists():
        return {"rows": []}
    import pandas as pd
    df = pd.read_csv(path)
    df = df.where(pd.notnull(df), None)
    return {"rows": df.to_dict(orient="records")}


@app.get("/api/calibration")
def calibration():
    path = config.RESULTS_DIR / "judge_calibration.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/raw/{strategy}")
def raw_results(strategy: str, limit: int = 500, offset: int = 0):
    if strategy not in config.STRATEGIES:
        raise HTTPException(status_code=404, detail=f"Unknown strategy '{strategy}'")
    path = config.RAW_OUTPUTS_DIR / f"{strategy}.jsonl"
    rows = _read_jsonl(path)
    return {"total": len(rows), "rows": rows[offset: offset + limit]}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    q = bus.subscribe()
    try:
        await websocket.send_json({
            "type": "hello",
            "status": job.state.snapshot(),
            "history": list(bus.history),
        })
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
