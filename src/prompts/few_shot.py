"""Few-shot prompting strategy: same instruction as zero-shot, preceded by
3 fixed exemplars (including one 'context doesn't support an answer' case)
demonstrating the desired grounded-answer behavior. Exemplars are on topics
disjoint from the evaluation set to avoid contaminating results."""
from langchain_core.prompts import ChatPromptTemplate

from .zero_shot import SYSTEM_PROMPT

FEW_SHOT_EXAMPLES = [
    {
        "context": "Alexander Graham Bell was awarded the first US patent for the "
                   "telephone in 1876. He conducted his work in Boston, Massachusetts.",
        "question": "Who received the first US patent for the telephone?",
        "answer": "Alexander Graham Bell received the first US patent for the "
                  "telephone, in 1876.",
    },
    {
        "context": "In computer science, an algorithm is a finite, well-defined "
                   "sequence of steps used to solve a problem or perform a computation.",
        "question": "What is an algorithm?",
        "answer": "An algorithm is a finite, well-defined sequence of steps for "
                  "solving a problem or performing a computation.",
    },
    {
        "context": "The Great Barrier Reef, located off the coast of Queensland, "
                   "Australia, is the world's largest coral reef system.",
        "question": "What is the population of clownfish in the Great Barrier Reef?",
        "answer": "I don't know based on the provided context.",
    },
]

_example_messages = []
for _ex in FEW_SHOT_EXAMPLES:
    _example_messages.append(
        ("human", f"Context:\n{_ex['context']}\n\nQuestion: {_ex['question']}\n\nAnswer:")
    )
    _example_messages.append(("ai", _ex["answer"]))

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    *_example_messages,
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
