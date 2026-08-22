from langchain_core.documents import Document

import config
from src.ingest import chunk_documents


def test_chunk_documents_splits_long_text():
    text = "This is a sentence about foo. " * 100
    docs = [Document(page_content=text)]
    chunks = chunk_documents(docs)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.page_content) <= config.CHUNK_SIZE + 100  # separator slack


def test_chunk_documents_assigns_chunk_ids():
    docs = [Document(page_content="short text")]
    chunks = chunk_documents(docs)
    assert all("chunk_id" in c.metadata for c in chunks)
    assert [c.metadata["chunk_id"] for c in chunks] == list(range(len(chunks)))


def test_chunk_documents_preserves_short_text_unsplit():
    docs = [Document(page_content="A short passage that fits in one chunk.")]
    chunks = chunk_documents(docs)
    assert len(chunks) == 1
