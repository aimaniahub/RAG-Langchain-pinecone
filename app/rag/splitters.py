"""Text splitters — LangChain RecursiveCharacterTextSplitter (Phase 2)."""

from __future__ import annotations

from app.config import settings
from app.core.logging import get_logger
from app.models.domain import DocumentChunk

logger = get_logger("rag.splitters")


def split_documents(docs: list[DocumentChunk]) -> list[DocumentChunk]:
    """Split documents into overlapping chunks with stable metadata."""
    if not docs:
        return []

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[DocumentChunk] = []
    for doc in docs:
        pieces = splitter.split_text(doc.content)
        doc_id = str(doc.metadata.get("doc_id", "doc"))
        for idx, piece in enumerate(pieces):
            text = piece.strip()
            if not text:
                continue
            chunk_id = f"{doc_id}_{idx}"
            chunks.append(
                DocumentChunk(
                    content=text,
                    chunk_id=chunk_id,
                    metadata={
                        **doc.metadata,
                        "doc_id": doc_id,
                        "chunk_index": idx,
                        "chunk_id": chunk_id,
                    },
                )
            )

    logger.info(
        "split_documents: %s doc(s) → %s chunk(s) (size=%s overlap=%s)",
        len(docs),
        len(chunks),
        settings.chunk_size,
        settings.chunk_overlap,
    )
    return chunks
