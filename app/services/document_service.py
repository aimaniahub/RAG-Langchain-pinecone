"""Document upload, storage, and auto-embed into Pinecone."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import IngestError, NotConfiguredError
from app.core.logging import get_logger
from app.db.models import Document, IngestJob, UsageEvent
from app.rag.loaders import load_from_bytes
from app.rag.splitters import split_documents
from app.services.cache_service import cache_service
from app.services.embedding_service import EmbeddingService
from app.storage.s3_client import ObjectStorage, get_storage
from app.vectorstore.pinecone_client import PineconeClient

logger = get_logger("services.document")

ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


class DocumentService:
    def __init__(
        self,
        db: Session,
        storage: ObjectStorage | None = None,
        embedding_service: EmbeddingService | None = None,
        pinecone_client: PineconeClient | None = None,
    ) -> None:
        self.db = db
        self.storage = storage or get_storage()
        self.embedding_service = embedding_service or EmbeddingService()
        self.pinecone_client = pinecone_client or PineconeClient()

    def list_documents(
        self,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[Document]:
        q = self.db.query(Document).order_by(Document.created_at.desc())
        if tenant_id:
            q = q.filter(Document.tenant_id == tenant_id)
        return q.limit(limit).all()

    def get(self, document_id: str, tenant_id: str | None = None) -> Document | None:
        doc = self.db.get(Document, document_id)
        if not doc:
            return None
        if tenant_id and doc.tenant_id and doc.tenant_id != tenant_id:
            return None
        return doc

    def upload(
        self,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        namespace: str | None = None,
        uploaded_by: str | None = None,
        process_now: bool = True,
        tenant_id: str | None = None,
    ) -> Document:
        if not data:
            raise IngestError("Empty file")
        if len(data) > settings.max_upload_bytes:
            raise IngestError(f"File too large (max {settings.max_upload_bytes} bytes)")

        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise IngestError(f"Unsupported type {suffix}. Allowed: {sorted(ALLOWED_SUFFIXES)}")

        doc_id = str(uuid.uuid4())
        ns = namespace or settings.pinecone_namespace or "default"
        safe_name = Path(filename).name.replace(" ", "_")
        # Company-wise layout in S3/local:
        #   companies/{tenant_id|slug}/documents/{doc_id}/{filename}
        folder = tenant_id or "platform"
        if tenant_id:
            try:
                from app.db.models import Tenant

                t = self.db.get(Tenant, tenant_id)
                if t and t.slug:
                    folder = t.slug
            except Exception:  # noqa: BLE001
                folder = tenant_id
        storage_key = f"companies/{folder}/documents/{doc_id}/{safe_name}"

        self.storage.put_bytes(storage_key, data, content_type=content_type)

        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=safe_name,
            content_type=content_type,
            size_bytes=len(data),
            storage_key=storage_key,
            storage_backend=settings.storage_backend,
            status="uploaded",
            namespace=ns,
            uploaded_by=uploaded_by,
        )
        job = IngestJob(document_id=doc_id, status="pending")
        self.db.add(doc)
        self.db.add(job)
        self.db.commit()
        self.db.refresh(doc)

        if process_now:
            self.process_document(doc_id)

        return self.get(doc_id) or doc

    def process_document(self, document_id: str) -> Document:
        """Load from storage → chunk → embed → Pinecone."""
        if not settings.is_pinecone_configured:
            raise NotConfiguredError("Pinecone")

        doc = self.get(document_id)
        if not doc:
            raise IngestError("Document not found")

        job = (
            self.db.query(IngestJob)
            .filter(IngestJob.document_id == document_id)
            .order_by(IngestJob.created_at.desc())
            .first()
        )
        if job is None:
            job = IngestJob(document_id=document_id, status="pending")
            self.db.add(job)

        job.status = "running"
        job.attempts = (job.attempts or 0) + 1
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        doc.status = "processing"
        doc.error = None
        self.db.commit()

        try:
            raw = self.storage.get_bytes(doc.storage_key)
            chunks = load_from_bytes(
                doc.filename,
                raw,
                metadata={
                    "source": doc.filename,
                    "document_id": doc.id,
                    "doc_id": doc.id,
                },
            )
            split = split_documents(chunks)
            if not split:
                raise IngestError("No chunks produced")
            if len(split) > settings.max_chunks_per_ingest:
                raise IngestError(
                    f"Too many chunks ({len(split)}). Max {settings.max_chunks_per_ingest}."
                )

            # enrich metadata
            for c in split:
                c.metadata["document_id"] = doc.id
                c.metadata["source"] = doc.filename

            vectors = self.embedding_service.embed_texts([c.content for c in split])
            result = self.pinecone_client.upsert(
                chunks=split,
                vectors=vectors,
                namespace=doc.namespace,
            )
            upserted = int(result.get("upserted_count") or 0)

            doc.chunk_count = len(split)
            doc.vector_count = upserted
            doc.status = "ready"
            job.status = "completed"
            job.finished_at = datetime.now(timezone.utc)
            cache_service.bump_generation(doc.namespace)

            self.db.add(
                UsageEvent(
                    event_type="ingest",
                    tenant_id=doc.tenant_id,
                    user_name=doc.uploaded_by,
                    document_id=doc.id,
                    latency_ms=None,
                    model=settings.embedding_model,
                )
            )
            self.db.commit()
            logger.info(
                "document processed id=%s chunks=%s vectors=%s",
                doc.id,
                doc.chunk_count,
                doc.vector_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("document process failed id=%s", document_id)
            doc.status = "failed"
            doc.error = str(exc)[:2000]
            job.status = "failed"
            job.error = str(exc)[:2000]
            job.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

        return doc

    def delete_document(self, document_id: str) -> None:
        doc = self.get(document_id)
        if not doc:
            raise IngestError("Document not found")
        try:
            self.storage.delete(doc.storage_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("storage delete failed: %s", exc)
        self.db.query(IngestJob).filter(IngestJob.document_id == document_id).delete()
        self.db.delete(doc)
        self.db.commit()
        cache_service.bump_generation(doc.namespace)
