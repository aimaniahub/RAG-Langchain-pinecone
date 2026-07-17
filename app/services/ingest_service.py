"""Document ingest orchestration — Phase 2 full pipeline."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.exceptions import IngestError, NotConfiguredError
from app.core.logging import get_logger
from app.models.schemas import IngestRequest, IngestResponse
from app.rag.loaders import load_from_bytes, load_from_paths, load_texts
from app.rag.splitters import split_documents
from app.services.embedding_service import EmbeddingService
from app.vectorstore.pinecone_client import PineconeClient

logger = get_logger("services.ingest")


class IngestService:
    """Load → split → embed (HF free) → upsert Pinecone."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        pinecone_client: PineconeClient | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.pinecone_client = pinecone_client or PineconeClient()

    def ingest(self, request: IngestRequest) -> IngestResponse:
        """Accept texts and/or file paths; run the real pipeline."""
        if not settings.is_pinecone_configured:
            raise NotConfiguredError("Pinecone")

        texts = list(request.texts or [])
        paths = list(request.file_paths or [])
        if not texts and not paths:
            raise IngestError("Provide at least one of: texts, file_paths")

        docs = []
        if texts:
            docs.extend(load_texts(texts, metadata=request.metadata))
        if paths:
            docs.extend(load_from_paths(paths, metadata=request.metadata))

        if not docs:
            raise IngestError("No valid documents to ingest (empty after cleaning)")

        chunks = split_documents(docs)
        if not chunks:
            raise IngestError("No chunks produced from documents")

        if len(chunks) > settings.max_chunks_per_ingest:
            raise IngestError(
                f"Too many chunks ({len(chunks)}). "
                f"Max allowed per request is {settings.max_chunks_per_ingest}. "
                "Split the upload or reduce document size."
            )

        ns = (request.namespace or settings.pinecone_namespace or "").strip()
        if not ns:
            raise IngestError(
                "Missing namespace. Client ingest must use a company API key."
            )
        # Stamp tenant metadata if caller put it in request.metadata
        meta = dict(request.metadata or {})
        for c in chunks:
            c.metadata.update({k: v for k, v in meta.items() if k not in c.metadata})
            c.metadata.setdefault("namespace", ns)
            if meta.get("tenant_id"):
                c.metadata["tenant_id"] = str(meta["tenant_id"])

        vectors = self.embedding_service.embed_texts([c.content for c in chunks])
        result = self.pinecone_client.upsert(
            chunks=chunks,
            vectors=vectors,
            namespace=ns,
        )
        ns = result.get("namespace") or ns

        from app.services.cache_service import cache_service

        cache_service.bump_generation(str(ns))

        logger.info(
            "ingest ok docs=%s chunks=%s upserted=%s ns=%s",
            len(docs),
            len(chunks),
            result.get("upserted_count", 0),
            ns,
        )
        return IngestResponse(
            status="ok",
            message="Ingested successfully",
            documents_received=len(docs),
            chunks_created=len(chunks),
            vectors_upserted=int(result.get("upserted_count") or 0),
            namespace=str(ns),
            phase=settings.phase,
        )

    def ingest_file_upload(
        self,
        filename: str,
        data: bytes,
        metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> IngestResponse:
        """Ingest a single uploaded file (txt/md/pdf)."""
        if not settings.is_pinecone_configured:
            raise NotConfiguredError("Pinecone")

        ns = (namespace or settings.pinecone_namespace or "").strip()
        if not ns:
            raise IngestError("Missing namespace. Use a company API key for file ingest.")
        meta = dict(metadata or {})
        meta.setdefault("namespace", ns)
        docs = load_from_bytes(filename, data, metadata=meta)
        chunks = split_documents(docs)
        if not chunks:
            raise IngestError("No chunks produced from uploaded file")
        if len(chunks) > settings.max_chunks_per_ingest:
            raise IngestError(
                f"Too many chunks ({len(chunks)}). "
                f"Max allowed per request is {settings.max_chunks_per_ingest}."
            )
        for c in chunks:
            c.metadata.setdefault("namespace", ns)
            if meta.get("tenant_id"):
                c.metadata["tenant_id"] = str(meta["tenant_id"])
            if meta.get("tenant_slug"):
                c.metadata["tenant_slug"] = str(meta["tenant_slug"])

        vectors = self.embedding_service.embed_texts([c.content for c in chunks])
        result = self.pinecone_client.upsert(
            chunks=chunks,
            vectors=vectors,
            namespace=ns,
        )
        ns = str(result.get("namespace") or ns)
        from app.services.cache_service import cache_service

        cache_service.bump_generation(ns)
        return IngestResponse(
            status="ok",
            message=f"Ingested file {filename}",
            documents_received=len(docs),
            chunks_created=len(chunks),
            vectors_upserted=int(result.get("upserted_count") or 0),
            namespace=str(ns),
            phase=settings.phase,
        )

    def ingest_texts(
        self,
        docs: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> IngestResponse:
        """Convenience wrapper for scripts/tests."""
        return self.ingest(IngestRequest(texts=docs, metadata=metadata or {}))
