import pytest
from pydantic import ValidationError

from src.schemas import StructuredRAGAnswer, HallucinationJudgement, ClaimCheck


def test_structured_answer_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        StructuredRAGAnswer(answer="x", supporting_quotes=[], is_grounded=True, confidence=1.5)


def test_structured_answer_accepts_valid_payload():
    obj = StructuredRAGAnswer(
        answer="Paris is the capital of France.",
        supporting_quotes=["Paris is the capital of France."],
        is_grounded=True,
        confidence=0.95,
    )
    assert obj.is_grounded is True


def test_hallucination_judgement_rejects_unknown_label():
    with pytest.raises(ValidationError):
        HallucinationJudgement(
            claims=[],
            label="Not A Real Label",
            is_hallucinated=True,
            is_correct=False,
            rationale="r",
        )


def test_hallucination_judgement_requires_claims():
    with pytest.raises(ValidationError):
        HallucinationJudgement(
            label="Baseless Information",
            is_hallucinated=True,
            is_correct=False,
            rationale="r",
        )


def test_hallucination_judgement_accepts_valid_payload():
    obj = HallucinationJudgement(
        claims=[
            ClaimCheck(claim="Paris is the capital of France.",
                       supported_by_context=True, contradicts_context=False),
            ClaimCheck(claim="The Eiffel Tower is 500 metres tall.",
                       supported_by_context=False, contradicts_context=True),
        ],
        label="Evident Conflict",
        is_hallucinated=True,
        is_correct=False,
        rationale="One claim contradicts the context.",
    )
    assert obj.label == "Evident Conflict"
    assert len(obj.claims) == 2
