"""
Loads and normalizes the RAGTruth QA subset (wandb/RAGTruth-processed on
Hugging Face) into flat JSONL files consumed by the rest of the pipeline.

Known schema of wandb/RAGTruth-processed (train+test, 17,790 rows total):
    id, query, context, output, task_type, quality, model, temperature,
    hallucination_labels, hallucination_labels_processed, input_str

We keep only task_type == "QA" rows because that is the only RAGTruth
subtype that resembles a real retrieval-augmented question-answering
scenario (Summary/Data2txt don't have a natural "question").

IMPORTANT DESIGN NOTE:
RAGTruth's `context` field is the passage that was shown to *its own*
annotated models (GPT-4, Llama, Mistral, ...), and `hallucination_labels`
describe errors in *their* responses -- not in the answers our pipeline
will generate with gpt-4o-mini + 4 prompt strategies. So this loader
produces two distinct artifacts:

  1. `ragtruth_qa.jsonl`   -- (query, context, reference_answer) triples
                              used as the *benchmark eval set*: our own
                              RAG pipeline answers these questions fresh,
                              and we score those NEW answers.
  2. `judge_calibration.jsonl` -- RAGTruth's (context, output,
                              hallucination_labels) triples, kept as-is,
                              used ONLY to sanity-check that our LLM
                              hallucination judge (src/evaluate.py) agrees
                              with human annotators before we trust it to
                              grade our own pipeline's answers.

Also writes `corpus.jsonl`: the de-duplicated set of context passages
across the sampled QA rows. This is the raw document collection that
src/ingest.py chunks/embeds/indexes -- we deliberately do NOT reuse
RAGTruth's own chunking or retrieval, only its questions, gold passages,
and human labels.
"""
import argparse
import json
import random
import sys

import config


def _get_field(row: dict, *candidates, default=None):
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return default


def _flatten_context(context) -> str:
    """RAGTruth `context` is usually a string, but be defensive in case a
    given row stores a list of passages instead."""
    if isinstance(context, list):
        return "\n\n".join(str(c) for c in context)
    return str(context)


def _has_hallucination(row: dict) -> bool:
    """wandb/RAGTruth-processed stores `hallucination_labels_processed` as an
    aggregate-count dict, e.g. {'evident_conflict': 0, 'baseless_info': 1} --
    a bare `bool(dict)` check is always True for a non-empty dict regardless
    of whether the counts are zero, so we must sum the counts explicitly.
    `hallucination_labels` (the raw per-span label list) is used as a
    fallback for schema variants that don't provide the processed counts.
    """
    proc = row.get("hallucination_labels_processed")
    if isinstance(proc, dict):
        return sum(v for v in proc.values() if isinstance(v, (int, float))) > 0
    if isinstance(proc, list):
        return len(proc) > 0

    labels = row.get("hallucination_labels")
    if labels is None:
        return False
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except json.JSONDecodeError:
            return bool(labels.strip())
    return bool(labels)


def _load_from_huggingface():
    from datasets import load_dataset

    print(f"Downloading {config.HF_DATASET_NAME} from Hugging Face ...")
    ds = load_dataset(config.HF_DATASET_NAME)
    rows = []
    for split in ds.keys():
        rows.extend(ds[split])
    print(f"Loaded {len(rows)} total rows across splits: {list(ds.keys())}")
    return rows


def _load_fixture():
    """Small, deterministic, offline stand-in with the same schema, used
    when the real dataset can't be downloaded (no network / no HF access).
    Lets the rest of the pipeline be built, tested, and demoed without
    connectivity. Clearly NOT a substitute for running the real benchmark.
    """
    print("!! Falling back to the bundled OFFLINE FIXTURE. Results produced from "
          "this data are for pipeline smoke-testing only, NOT for the report. "
          "Run with a working internet connection to use the real RAGTruth data.")
    fixture_path = config.ROOT_DIR / "tests" / "fixtures" / "ragtruth_fixture.jsonl"
    rows = []
    with open(fixture_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_dataset(sample_size=None, calibration_size=None, seed=None, use_fixture=False):
    sample_size = sample_size or config.EVAL_SAMPLE_SIZE
    calibration_size = calibration_size or config.CALIBRATION_SAMPLE_SIZE
    seed = seed if seed is not None else config.RANDOM_SEED

    if use_fixture:
        rows = _load_fixture()
    else:
        try:
            rows = _load_from_huggingface()
        except Exception as exc:  # noqa: BLE001 - any network/auth/schema failure
            print(f"Could not load '{config.HF_DATASET_NAME}' from Hugging Face: {exc}",
                  file=sys.stderr)
            rows = _load_fixture()

    qa_rows = [r for r in rows if _get_field(r, "task_type") == config.HF_TASK_TYPE_FILTER]
    print(f"{len(qa_rows)} rows have task_type == '{config.HF_TASK_TYPE_FILTER}'")
    if not qa_rows:
        raise RuntimeError(
            f"No rows found with task_type == '{config.HF_TASK_TYPE_FILTER}'. "
            "Inspect the dataset schema (see README) and adjust "
            "config.HF_TASK_TYPE_FILTER / the field names in data_loader.py."
        )

    rng = random.Random(seed)
    rng.shuffle(qa_rows)

    # Calibration rows: prefer a balanced mix of hallucinated / clean examples
    # so the judge's agreement score isn't trivially inflated by an
    # all-clean or all-hallucinated calibration set.
    hallucinated = [r for r in qa_rows if _has_hallucination(r)]
    clean = [r for r in qa_rows if not _has_hallucination(r)]
    half = calibration_size // 2
    calibration_rows = hallucinated[:half] + clean[:calibration_size - half]
    rng.shuffle(calibration_rows)

    used_ids = {id(r) for r in calibration_rows}
    remaining = [r for r in qa_rows if id(r) not in used_ids]
    eval_rows = remaining[:sample_size]

    if len(eval_rows) < sample_size:
        print(f"Warning: only {len(eval_rows)} eval rows available "
              f"(requested {sample_size}).", file=sys.stderr)

    # --- Write benchmark eval set --------------------------------------
    normalized_eval = []
    for r in eval_rows:
        query = _get_field(r, "query", "prompt", "question")
        context = _flatten_context(_get_field(r, "context", "source_info", default=""))
        reference_answer = _get_field(r, "output", "response", "reference_answer")
        normalized_eval.append({
            "id": _get_field(r, "id", default=len(normalized_eval)),
            "query": query,
            "reference_context": context,
            "reference_answer": reference_answer,
        })

    with open(config.PROCESSED_DATASET_PATH, "w", encoding="utf-8") as f:
        for row in normalized_eval:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(normalized_eval)} eval rows -> {config.PROCESSED_DATASET_PATH}")

    # --- Write judge calibration set (RAGTruth's own labeled outputs) --
    normalized_cal = []
    for r in calibration_rows:
        # Prefer the raw per-span label list (richer: text spans + label_type)
        # over the aggregate {evident_conflict, baseless_info} count dict.
        labels = r.get("hallucination_labels")
        if labels is None or labels == "[]":
            labels = r.get("hallucination_labels_processed") or []
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except json.JSONDecodeError:
                labels = [{"raw": labels}]
        normalized_cal.append({
            "id": _get_field(r, "id", default=len(normalized_cal)),
            "query": _get_field(r, "query", "prompt", "question"),
            "context": _flatten_context(_get_field(r, "context", "source_info", default="")),
            "response": _get_field(r, "output", "response"),
            "is_hallucinated": _has_hallucination(r),
            "gold_labels": labels,
        })

    with open(config.CALIBRATION_SET_PATH, "w", encoding="utf-8") as f:
        for row in normalized_cal:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(normalized_cal)} calibration rows -> {config.CALIBRATION_SET_PATH}")

    # --- Write de-duplicated corpus for ingestion -----------------------
    corpus_path = config.DATA_PROCESSED_DIR / "corpus.jsonl"
    seen = set()
    corpus_docs = []
    for r in normalized_eval + normalized_cal:
        ctx = r.get("reference_context") or r.get("context")
        if ctx and ctx not in seen:
            seen.add(ctx)
            corpus_docs.append({"doc_id": len(corpus_docs), "text": ctx})

    with open(corpus_path, "w", encoding="utf-8") as f:
        for doc in corpus_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"Wrote {len(corpus_docs)} unique corpus documents -> {corpus_path}")

    return normalized_eval, normalized_cal, corpus_docs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=config.EVAL_SAMPLE_SIZE)
    parser.add_argument("--calibration-size", type=int, default=config.CALIBRATION_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=config.RANDOM_SEED)
    parser.add_argument("--fixture", action="store_true",
                         help="Force use of the bundled offline fixture instead of "
                              "downloading from Hugging Face.")
    args = parser.parse_args()
    build_dataset(args.sample_size, args.calibration_size, args.seed, use_fixture=args.fixture)
