"""Chain-of-Thought prompting strategy: the model must reason step-by-step,
checking each claim against the retrieved context, before committing to a
final answer. Reasoning and answer are separated with tags so the
reasoning tokens can be measured (cost/latency) without being scored as
the answer itself."""
import re

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = (
    "You are a careful assistant. Think through the question step-by-step "
    "using ONLY the provided context before answering, explicitly checking "
    "each claim you plan to make against the context.\n\n"
    "First, write your reasoning inside <reasoning></reasoning> tags.\n"
    "Then, write your final answer inside <answer></answer> tags.\n"
    "The <answer> must be a concise direct answer with no extra commentary. "
    "If the context does not support an answer, the <answer> must be exactly: "
    "\"I don't know based on the provided context.\""
)

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])

_REASONING_RE = re.compile(r"<reasoning>(.*?)</reasoning>", re.DOTALL | re.IGNORECASE)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)


def _parse(text: str) -> tuple[str, str]:
    reasoning_match = _REASONING_RE.search(text)
    answer_match = _ANSWER_RE.search(text)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else None
    answer = answer_match.group(1).strip() if answer_match else text.strip()
    return answer, reasoning


def invoke(llm, context: str, question: str) -> dict:
    chain = PROMPT | llm
    response = chain.invoke({"context": context, "question": question})
    answer, reasoning = _parse(response.content)
    return {
        "answer": answer,
        "reasoning": reasoning,
        "structured": None,
        "response": response,
    }
