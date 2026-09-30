"""
Central configuration for the Prompt Engineering Strategy Benchmark.

Every constant in this file is a *control variable* held fixed across all
four prompting strategies (zero-shot, few-shot, chain-of-thought,
structured-output). The only thing that is allowed to vary between
experiment runs is the prompt template / output parser used in
src/prompts/*.py. This is what makes the comparison fair.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
# RAG_WORKDIR redirects every generated artifact (processed data, the Chroma
# vector store, results) under an alternate root instead of the project
# directory. Use this for demos / live runs you do NOT want to overwrite the
# real committed results with -- e.g.
#   $env:RAG_WORKDIR = "demo_workspace"; python scripts/run_webapp.py
# Leave unset for the real thing; the defaults (project-root-relative) are
# unchanged.
ROOT_DIR = Path(__file__).resolve().parent
_workdir_override = os.getenv("RAG_WORKDIR")
WORK_ROOT = (ROOT_DIR / _workdir_override).resolve() if _workdir_override else ROOT_DIR

DATA_RAW_DIR = WORK_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = WORK_ROOT / "data" / "processed"
CHROMA_PERSIST_DIR = WORK_ROOT / "chroma_store"
RESULTS_DIR = WORK_ROOT / "results"
RAW_OUTPUTS_DIR = RESULTS_DIR / "raw_outputs"
CHARTS_DIR = RESULTS_DIR / "charts"

for _d in (DATA_RAW_DIR, DATA_PROCESSED_DIR, CHROMA_PERSIST_DIR, RAW_OUTPUTS_DIR, CHARTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

PROCESSED_DATASET_PATH = DATA_PROCESSED_DIR / "ragtruth_qa.jsonl"
CALIBRATION_SET_PATH = DATA_PROCESSED_DIR / "judge_calibration.jsonl"

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Dataset
HF_DATASET_NAME = "wandb/RAGTruth-processed"
HF_TASK_TYPE_FILTER = "QA"          # RAGTruth task types: QA, Summary, Data2txt
EVAL_SAMPLE_SIZE = 60                # examples run through the full 4-strategy benchmark
CALIBRATION_SAMPLE_SIZE = 30         # examples used to sanity-check the hallucination judge
RANDOM_SEED = 42

# Chunking (control variable — identical for every strategy)
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Embeddings (control variable)
EMBEDDING_MODEL = "text-embedding-3-small"

# Vector store (control variable)
CHROMA_COLLECTION_NAME = "ragtruth_corpus"
TOP_K = 4

# LLM (control variable — same model/temperature for every strategy AND for
# generation vs. the judge, so grading isn't a confound)
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0.0
JUDGE_MODEL = "gpt-4o-mini"
JUDGE_TEMPERATURE = 0.0

# Prompting strategies under test
STRATEGIES = ["zero_shot", "few_shot", "chain_of_thought", "structured_output"]


# Pricing (USD / 1M tokens) — used only for the cost-comparison chart.
# Update if OpenAI pricing changes; see https://openai.com/api/pricing
PRICING_PER_1M_TOKENS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}
