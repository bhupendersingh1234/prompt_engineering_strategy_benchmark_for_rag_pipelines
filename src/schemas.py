"""Pydantic schemas shared across the pipeline."""
from typing import Literal
from pydantic import BaseModel, Field


class StructuredRAGAnswer(BaseModel):
    """Enforced output shape for the 'structured_output' prompting strategy.

    Forcing the model to cite supporting quotes and self-report groundedness
    is the mechanism this strategy uses to try to reduce hallucination --
    it can't emit free-form prose it hasn't tied back to a quote.
    """
    answer: str = Field(description="A concise, direct answer to the user's question.")
    supporting_quotes: list[str] = Field(
        default_factory=list,
        description="Exact quotes copied verbatim from the retrieved context that "
                     "justify the answer. Empty if the context does not support an answer.",
    )
    is_grounded: bool = Field(
        description="True only if every claim in `answer` is directly supported by "
                     "`supporting_quotes`. False if the answer relies on outside "
                     "knowledge or the context is insufficient.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model's self-reported confidence that `answer` is correct and grounded.",
    )


class ClaimCheck(BaseModel):
    """One atomic factual claim extracted from a judged answer. Forcing the
    judge to enumerate and check claims individually (rather than reading
    the answer holistically) is what catches a single unsupported clause
    buried inside an otherwise-accurate long answer -- see the
    `calibrate_judge` docstring in src/evaluate.py for why this matters."""
    claim: str = Field(description="One atomic factual claim from the answer, as a short sentence.")
    supported_by_context: bool = Field(
        description="True if this exact claim is stated in or directly inferable from the context."
    )
    contradicts_context: bool = Field(
        description="True if this exact claim directly contradicts the context."
    )


class HallucinationJudgement(BaseModel):
    """Output schema for the LLM-as-judge used in src/evaluate.py. Mirrors
    RAGTruth's own label taxonomy so judge outputs are directly comparable
    to RAGTruth's human annotations during calibration."""
    claims: list[ClaimCheck] = Field(
        description="Every atomic factual claim in the answer, each checked individually "
                     "against the context. Populate this BEFORE deciding `label` -- a long "
                     "answer with five correct claims and one unsupported claim must still "
                     "be flagged as hallucinated because of that one claim.",
    )
    label: Literal["Evident Conflict", "Baseless Information", "No Hallucination"] = Field(
        description="'Evident Conflict' if ANY claim contradicts the context, "
                     "'Baseless Information' if ANY claim is unsupported (and none "
                     "contradict), otherwise 'No Hallucination'."
    )
    is_hallucinated: bool = Field(description="True if label != 'No Hallucination'.")
    is_correct: bool = Field(
        description="True if the answer correctly and adequately answers the "
                     "question given the reference answer, independent of grounding."
    )
    rationale: str = Field(description="One or two sentence justification.")
