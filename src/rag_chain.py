"""
The RAG orchestrator. Retrieval (retriever), generation model (llm), top-k,
chunking and embeddings are all fixed control variables built once in
src/ingest.py. The ONLY thing that changes per experiment run is which
prompt-strategy module (src/prompts/*.py) formats the context+question into
a prompt and parses the response. This module wires those two fixed and
variable halves together and measures latency/token cost uniformly so the
four strategies are compared on equal footing.
"""
import time
from dataclasses import dataclass, field

from langchain_community.callbacks.manager import get_openai_callback
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI

import config
from src.prompts import STRATEGY_MODULES


def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(f"[{i+1}] {d.page_content}" for i, d in enumerate(docs))


@dataclass
class RAGResult:
    strategy: str
    query: str
    context_docs: list[Document]
    context_text: str
    answer: str
    reasoning: str | None
    structured: object | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    estimated_cost_usd: float = 0.0
    error: str | None = None


def get_llm(temperature: float = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.LLM_MODEL,
        temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
        api_key=config.OPENAI_API_KEY,
    )


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = config.PRICING_PER_1M_TOKENS.get(model)
    if not pricing:
        return 0.0
    return (prompt_tokens / 1_000_000) * pricing["input"] + \
           (completion_tokens / 1_000_000) * pricing["output"]


def run_strategy(strategy: str, question: str, retriever, llm: ChatOpenAI = None) -> RAGResult:
    if strategy not in STRATEGY_MODULES:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from {list(STRATEGY_MODULES)}")

    llm = llm or get_llm()
    module = STRATEGY_MODULES[strategy]

    docs = retriever.invoke(question)
    context_text = format_docs(docs)

    start = time.perf_counter()
    error = None
    prompt_tokens = completion_tokens = total_tokens = 0
    answer, reasoning, structured = "", None, None

    try:
        with get_openai_callback() as cb:
            out = module.invoke(llm, context_text, question)
        answer = out["answer"]
        reasoning = out.get("reasoning")
        structured = out.get("structured")
        prompt_tokens = cb.prompt_tokens
        completion_tokens = cb.completion_tokens
        total_tokens = cb.total_tokens
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    latency = time.perf_counter() - start

    return RAGResult(
        strategy=strategy,
        query=question,
        context_docs=docs,
        context_text=context_text,
        answer=answer,
        reasoning=reasoning,
        structured=structured,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_seconds=latency,
        estimated_cost_usd=_estimate_cost(config.LLM_MODEL, prompt_tokens, completion_tokens),
        error=error,
    )
