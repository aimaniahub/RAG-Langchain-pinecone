"""Free local HuggingFace embeddings via sentence-transformers (Phase 2).

Default model: sentence-transformers/all-MiniLM-L6-v2 (384-dim, no API key).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger

logger = get_logger("services.embedding")


@lru_cache
def _get_hf_embeddings() -> Any:
    """Lazy-load and cache the local HF embedding model."""
    from langchain_huggingface import HuggingFaceEmbeddings

    logger.info(
        "Loading free HF embedding model=%s device=%s",
        settings.embedding_model,
        settings.embedding_device,
    )
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": settings.embedding_device},
        encode_kwargs={"normalize_embeddings": True},
    )


class EmbeddingService:
    """Produces vector embeddings for chunks and queries (local HF, free)."""

    def __init__(self, client: Any | None = None) -> None:
        self.model = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _get_hf_embeddings()
        return self._client

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts; returns list of vectors."""
        if not texts:
            return []
        logger.info("embed_texts: %s text(s) model=%s", len(texts), self.model)
        try:
            vectors = self.client.embed_documents(texts)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Embedding failed")
            raise UpstreamError(
                f"Embedding model failed: {exc}",
                provider="huggingface",
            ) from exc
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        logger.info("embed_query model=%s len=%s", self.model, len(text))
        try:
            vector = self.client.embed_query(text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Query embedding failed")
            raise UpstreamError(
                f"Embedding model failed: {exc}",
                provider="huggingface",
            ) from exc
        return list(map(float, vector))
