"""Lightweight domain types (non-HTTP)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DocumentChunk:
    """A chunk of text ready for embedding / upsert."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_id: str | None = None


@dataclass(slots=True)
class RetrievalResult:
    """One hit from the vector store."""

    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
