"""Structured Output prompting strategy: the LLM must fill a Pydantic
schema (answer, supporting_quotes, is_grounded, confidence) via function
calling, forcing it to tie its answer to verbatim quotes from the context."""
from langchain_core.prompts import ChatPromptTemplate

from src.schemas import StructuredRAGAnswer

SYSTEM_PROMPT = (
    "Answer the question using ONLY the provided context and populate every "
    "field of the required schema.\n"
    "- `supporting_quotes` must be exact substrings copied verbatim from the context.\n"
    "- `is_grounded` must be true only if every claim in `answer` is directly "
    "supported by `supporting_quotes`.\n"
    "- If the context does not support an answer, set `is_grounded=false`, "
    "`confidence` low, `supporting_quotes=[]`, and `answer` to exactly: "
    "\"I don't know based on the provided context.\""
)

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])


def invoke(llm, context: str, question: str) -> dict:
    structured_llm = llm.with_structured_output(StructuredRAGAnswer)
    chain = PROMPT | structured_llm
    result: StructuredRAGAnswer = chain.invoke({"context": context, "question": question})
    return {
        "answer": result.answer,
        "reasoning": None,
        "structured": result,
        "response": result,
    }
