from src.prompts import chain_of_thought as cot
from src.prompts.few_shot import PROMPT as FEW_SHOT_PROMPT, FEW_SHOT_EXAMPLES
from src.prompts.zero_shot import PROMPT as ZERO_SHOT_PROMPT


def test_cot_parse_extracts_reasoning_and_answer():
    text = "<reasoning>Because the context says so.</reasoning><answer>Paris</answer>"
    answer, reasoning = cot._parse(text)
    assert answer == "Paris"
    assert reasoning == "Because the context says so."


def test_cot_parse_falls_back_to_raw_text_without_tags():
    text = "Just a plain answer with no tags."
    answer, reasoning = cot._parse(text)
    assert answer == text
    assert reasoning is None


def test_few_shot_prompt_includes_all_exemplars():
    messages = FEW_SHOT_PROMPT.format_messages(context="ctx", question="q?")
    joined = " ".join(m.content for m in messages)
    for ex in FEW_SHOT_EXAMPLES:
        assert ex["question"] in joined
        assert ex["answer"] in joined


def test_zero_shot_prompt_has_no_exemplars():
    messages = ZERO_SHOT_PROMPT.format_messages(context="ctx", question="q?")
    assert len(messages) == 2  # system + human only, no few-shot turns


def test_prompts_interpolate_context_and_question():
    messages = ZERO_SHOT_PROMPT.format_messages(context="MY_CONTEXT", question="MY_QUESTION")
    joined = " ".join(m.content for m in messages)
    assert "MY_CONTEXT" in joined
    assert "MY_QUESTION" in joined
