"""
Evaluation layer: two complementary measurements per generated answer.

1. RAGAS (reference-free): Faithfulness (is the answer supported by the
   retrieved context?) and Answer Relevancy (does the answer address the
   question?). Computed with the RAGAS library.

2. Custom hallucination judge: an LLM-as-judge prompted with RAGTruth's own
   label taxonomy ("Evident Conflict" / "Baseless Information" /
   "No Hallucination"), used to (a) sanity-check itself against RAGTruth's
   human annotations on the *calibration* set (src/data_loader.py) before
   we trust it, and (b) grade our own pipeline's freshly generated answers,
   which RAGTruth's original human labels cannot do since they were written
   for a different set of model outputs. See src/data_loader.py docstring.

The same judge model/temperature is used for every strategy (config.py),
so grading itself is not a confound.
"""
import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

import config
from src.schemas import HallucinationJudgement

JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checking judge for a retrieval-augmented QA system. "
    "You will be given a CONTEXT, a QUESTION, an ANSWER, and (optionally) a "
    "REFERENCE ANSWER.\n\n"
    "First, break the ANSWER down into its individual atomic factual claims "
    "and check EACH ONE against the CONTEXT individually -- do not judge the "
    "answer holistically. A long, mostly-accurate answer with even one "
    "unsupported or contradicted clause must still be flagged: do not let "
    "four accurate claims excuse a fifth one that isn't in the context.\n\n"
    "Then classify the ANSWER using this taxonomy, identical to the one used "
    "by the RAGTruth benchmark:\n"
    "- 'Evident Conflict': ANY claim directly contradicts the CONTEXT.\n"
    "- 'Baseless Information': ANY claim adds specifics (numbers, names, "
    "events, etc.) that are not present in or inferable from the CONTEXT, "
    "even if not directly contradictory, and no claim triggers 'Evident "
    "Conflict'.\n"
    "- 'No Hallucination': every claim is supported by the CONTEXT, OR the "
    "answer correctly declines to answer because the CONTEXT is insufficient.\n\n"
    "Also judge `is_correct`: whether the ANSWER adequately answers the "
    "QUESTION (compare against the REFERENCE ANSWER if one is given)."
)

JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", JUDGE_SYSTEM_PROMPT),
    ("human",
     "CONTEXT:\n{context}\n\n"
     "QUESTION:\n{question}\n\n"
     "ANSWER:\n{answer}\n\n"
     "REFERENCE ANSWER (may be empty):\n{reference_answer}"),
])


def get_judge_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=config.JUDGE_MODEL,
        temperature=config.JUDGE_TEMPERATURE,
        api_key=config.OPENAI_API_KEY,
    )


def judge_answer(judge_llm, context: str, question: str, answer: str,
                  reference_answer: str = "") -> HallucinationJudgement:
    structured_judge = judge_llm.with_structured_output(HallucinationJudgement)
    chain = JUDGE_PROMPT | structured_judge
    return chain.invoke({
        "context": context,
        "question": question,
        "answer": answer,
        "reference_answer": reference_answer or "",
    })


# ---------------------------------------------------------------------------
# Judge calibration against RAGTruth's human labels
# ---------------------------------------------------------------------------
def calibrate_judge(calibration_rows: list[dict], judge_llm=None, on_row=None) -> dict:
    """Runs the judge on RAGTruth's own (context, response) pairs and
    compares judge.is_hallucinated against RAGTruth's human `is_hallucinated`
    label. Returns agreement precision/recall/F1/accuracy so we can report
    how much to trust the judge before using it to grade our own pipeline.

    on_row(index, total, detail), if given, fires after each row is judged --
    used by webapp/backend to stream live calibration progress.
    """
    judge_llm = judge_llm or get_judge_llm()
    tp = fp = tn = fn = 0
    details = []

    for i, row in enumerate(calibration_rows):
        judgement = judge_answer(
            judge_llm,
            context=row["context"],
            question=row["query"],
            answer=row["response"],
        )
        predicted = judgement.is_hallucinated
        actual = row["is_hallucinated"]

        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and not actual:
            tn += 1
        else:
            fn += 1

        detail = {
            "id": row["id"],
            "actual_is_hallucinated": actual,
            "predicted_is_hallucinated": predicted,
            "predicted_label": judgement.label,
            "rationale": judgement.rationale,
        }
        details.append(detail)
        if on_row is not None:
            on_row(i + 1, len(calibration_rows), detail)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(calibration_rows) if calibration_rows else 0.0

    return {
        "n": len(calibration_rows),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
        "details": details,
    }


def _patch_ragas_vertexai_import_bug():
    """Every current release of `ragas` unconditionally does
    `from langchain_community.chat_models.vertexai import ChatVertexAI` deep in
    ragas/llms/base.py, purely to build a type-check isinstance() tuple -- it
    is never instantiated. `langchain-community` >= 0.4 removed that module as
    part of sunsetting itself in favor of standalone integration packages
    (we don't use Vertex AI anywhere in this project), so the import 404s and
    takes down all of `ragas` with it (see langchain-community issue #674 and
    ragas's hard import in llms/base.py). Since downgrading langchain-community
    to a version that still has the module cascades into breaking the modern
    langchain-core 1.x stack this project otherwise depends on, we register a
    harmless stub module in sys.modules so the import succeeds. Safe to remove
    once either project fixes this on their end.
    """
    import sys
    import types

    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
    except ModuleNotFoundError:
        stub = types.ModuleType("langchain_community.chat_models.vertexai")

        class ChatVertexAI:  # placeholder used only for isinstance() checks
            pass

        stub.ChatVertexAI = ChatVertexAI
        sys.modules["langchain_community.chat_models.vertexai"] = stub


# ---------------------------------------------------------------------------
# RAGAS (reference-free faithfulness + answer relevancy)
# ---------------------------------------------------------------------------
def compute_ragas_metrics(records: list[dict]) -> "pandas.DataFrame | None":
    """records: list of {question, answer, contexts: list[str]}.
    Returns a pandas DataFrame with per-row faithfulness/answer_relevancy
    scores, or None if RAGAS is unavailable / raises (e.g. API drift across
    ragas versions) -- logged clearly rather than silently swallowed.
    """
    try:
        _patch_ragas_vertexai_import_bug()
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import Faithfulness, AnswerRelevancy
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    except ImportError as exc:
        print(f"[evaluate] RAGAS not installed / import failed: {exc}")
        return None

    try:
        evaluator_llm = LangchainLLMWrapper(
            ChatOpenAI(model=config.JUDGE_MODEL, temperature=0.0, api_key=config.OPENAI_API_KEY)
        )
        evaluator_embeddings = LangchainEmbeddingsWrapper(
            OpenAIEmbeddings(model=config.EMBEDDING_MODEL, api_key=config.OPENAI_API_KEY)
        )
        dataset = EvaluationDataset.from_list([
            {
                "user_input": r["question"],
                "response": r["answer"],
                "retrieved_contexts": r["contexts"],
            }
            for r in records
        ])
        result = evaluate(
            dataset=dataset,
            metrics=[Faithfulness(), AnswerRelevancy()],
            llm=evaluator_llm,
            embeddings=evaluator_embeddings,
        )
        return result.to_pandas()
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluate] RAGAS scoring failed, skipping RAGAS metrics: {exc}")
        return None


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
