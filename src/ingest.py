"""
Builds the ONE shared vector index used by every prompting strategy.

Chunking, embedding model, and vector store are control variables (see
config.py) -- this module is run exactly once per experiment and its
output (a persisted Chroma collection) is then reused, read-only, by all
four prompt strategies so that retrieval quality can never explain a
difference in downstream metrics.
"""
import argparse
import json

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

import config


def load_corpus(corpus_path=None) -> list[Document]:
    corpus_path = corpus_path or (config.DATA_PROCESSED_DIR / "corpus.jsonl")
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"{corpus_path} not found. Run `python -m src.data_loader` first."
        )
    docs = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            docs.append(Document(page_content=row["text"], metadata={"doc_id": row["doc_id"]}))
    return docs


def chunk_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    for i, c in enumerate(chunks):
        c.metadata["chunk_id"] = i
    return chunks


def build_vectorstore(chunks: list[Document], persist: bool = True) -> Chroma:
    """(Re)builds the shared collection from scratch. `Chroma.from_documents`
    ADDS to whatever collection already exists at collection_name/persist_dir
    rather than replacing it -- re-running ingestion without clearing first
    silently accumulates duplicate/stale chunks from previous runs, which
    would quietly break the "identical retrieval for every strategy"
    guarantee this whole benchmark depends on. So we drop any existing
    collection of the same name first.
    """
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, api_key=config.OPENAI_API_KEY)
    existing = Chroma(
        collection_name=config.CHROMA_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(config.CHROMA_PERSIST_DIR) if persist else None,
    )
    existing.delete_collection()

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=config.CHROMA_COLLECTION_NAME,
        persist_directory=str(config.CHROMA_PERSIST_DIR) if persist else None,
    )
    return vectorstore


def get_vectorstore() -> Chroma:
    """Reopens the already-persisted collection (used by rag_chain.py so
    every strategy shares the exact same index without rebuilding it)."""
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, api_key=config.OPENAI_API_KEY)
    return Chroma(
        collection_name=config.CHROMA_COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(config.CHROMA_PERSIST_DIR),
    )


def get_retriever(k: int = None):
    vectorstore = get_vectorstore()
    return vectorstore.as_retriever(search_kwargs={"k": k or config.TOP_K})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=str, default=None)
    args = parser.parse_args()

    docs = load_corpus(args.corpus)
    print(f"Loaded {len(docs)} source documents.")
    chunks = chunk_documents(docs)
    print(f"Split into {len(chunks)} chunks "
          f"(chunk_size={config.CHUNK_SIZE}, overlap={config.CHUNK_OVERLAP}).")
    build_vectorstore(chunks)
    print(f"Persisted Chroma collection '{config.CHROMA_COLLECTION_NAME}' "
          f"to {config.CHROMA_PERSIST_DIR}")


if __name__ == "__main__":
    main()
