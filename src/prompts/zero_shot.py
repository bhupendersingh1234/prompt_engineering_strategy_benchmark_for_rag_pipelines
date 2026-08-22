"""Zero-shot prompting strategy: a single instruction, no examples."""
from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions using ONLY the "
    "provided context. If the context does not contain the answer, reply "
    "exactly: \"I don't know based on the provided context.\""
)

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"),
])


def invoke(llm, context: str, question: str) -> dict:
    chain = PROMPT | llm
    response = chain.invoke({"context": context, "question": question})
    return {
        "answer": response.content.strip(),
        "reasoning": None,
        "structured": None,
        "response": response,
    }
