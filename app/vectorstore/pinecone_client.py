"""Pinecone client wrapper — real upsert/query (Phase 2)."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.exceptions import NotConfiguredError, UpstreamError
from app.core.logging import get_logger
from app.models.domain import DocumentChunk, RetrievalResult

logger = get_logger("vectorstore.pinecone")

# Pinecone metadata string limit safety
_MAX_META_TEXT = 35000


class PineconeClient:
    """Thin wrapper around the official Pinecone SDK."""

    def __init__(self, index: Any | None = None) -> None:
        self.index_name = settings.pinecone_index_name
        self.namespace = settings.pinecone_namespace
        self._configured = settings.is_pinecone_configured
        self._index = index
        self._pc: Any | None = None
        logger.info(
            "PineconeClient init index=%s namespace=%s configured=%s",
            self.index_name,
            self.namespace,
            self._configured,
        )

    def _require_configured(self) -> None:
        if not self._configured:
            raise NotConfiguredError("Pinecone")

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        self._require_configured()
        try:
            from pinecone import Pinecone

            self._pc = Pinecone(api_key=settings.pinecone_api_key)
            self._index = self._pc.Index(self.index_name)
        except NotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to connect to Pinecone index")
            raise UpstreamError(
                f"Pinecone connection failed: {exc}",
                provider="pinecone",
            ) from exc
        return self._index

    def upsert(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Upsert chunk vectors with metadata (includes text for retrieval)."""
        if len(chunks) != len(vectors):
            raise UpstreamError(
                "chunks and vectors length mismatch",
                provider="pinecone",
            )
        if not chunks:
            return {
                "status": "ok",
                "upserted_count": 0,
                "namespace": namespace or self.namespace,
                "index": self.index_name,
            }

        ns = namespace or self.namespace
        index = self._get_index()

        records: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            vid = chunk.chunk_id or chunk.metadata.get("chunk_id")
            if not vid:
                vid = f"vec_{len(records)}"
            text = chunk.content[:_MAX_META_TEXT]
            meta = {
                k: v
                for k, v in chunk.metadata.items()
                if isinstance(v, (str, int, float, bool)) and k != "text"
            }
            meta["text"] = text
            records.append({"id": str(vid), "values": vector, "metadata": meta})

        try:
            # Batch in groups of 100
            upserted = 0
            batch_size = 100
            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]
                index.upsert(vectors=batch, namespace=ns)
                upserted += len(batch)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pinecone upsert failed")
            raise UpstreamError(
                f"Pinecone upsert failed: {exc}",
                provider="pinecone",
            ) from exc

        logger.info("pinecone upsert: %s vector(s) ns=%s", upserted, ns)
        return {
            "status": "ok",
            "upserted_count": upserted,
            "namespace": ns,
            "index": self.index_name,
        }

    def query(
        self,
        vector: list[float],
        top_k: int | None = None,
        namespace: str | None = None,
        *,
        tenant_id: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """Similarity search; returns content from metadata.text.

        Always pass company namespace. Prefer tenant_id filter so vectors from
        another company never leak even if a namespace was misconfigured.
        """
        k = top_k or settings.top_k
        ns = (namespace or self.namespace or "").strip() or "default"
        index = self._get_index()

        flt: dict[str, Any] | None = dict(metadata_filter) if metadata_filter else None
        if tenant_id:
            tid_filter = {"tenant_id": {"$eq": str(tenant_id)}}
            flt = {**(flt or {}), **tid_filter}

        try:
            kwargs: dict[str, Any] = {
                "vector": vector,
                "top_k": k,
                "namespace": ns,
                "include_metadata": True,
            }
            if flt:
                kwargs["filter"] = flt
            result = index.query(**kwargs)
        except Exception as exc:  # noqa: BLE001
            # Older indexes may lack tenant_id on all vectors — retry without filter
            if flt and tenant_id:
                logger.warning(
                    "pinecone query with tenant filter failed (%s); retry ns-only",
                    str(exc)[:120],
                )
                try:
                    result = index.query(
                        vector=vector,
                        top_k=k,
                        namespace=ns,
                        include_metadata=True,
                    )
                except Exception as exc2:  # noqa: BLE001
                    logger.exception("Pinecone query failed")
                    raise UpstreamError(
                        f"Pinecone query failed: {exc2}",
                        provider="pinecone",
                    ) from exc2
            else:
                logger.exception("Pinecone query failed")
                raise UpstreamError(
                    f"Pinecone query failed: {exc}",
                    provider="pinecone",
                ) from exc

        matches = getattr(result, "matches", None)
        if matches is None and isinstance(result, dict):
            matches = result.get("matches", [])
        matches = matches or []

        hits: list[RetrievalResult] = []
        for match in matches:
            if isinstance(match, dict):
                score = float(match.get("score") or 0.0)
                meta = dict(match.get("metadata") or {})
            else:
                score = float(getattr(match, "score", 0.0) or 0.0)
                raw_meta = getattr(match, "metadata", None) or {}
                meta = dict(raw_meta)

            # Drop any accidental cross-tenant hit if filter was skipped
            if tenant_id and meta.get("tenant_id") and str(meta.get("tenant_id")) != str(tenant_id):
                continue

            content = str(meta.pop("text", "") or "")
            hits.append(RetrievalResult(content=content, score=score, metadata=meta))

        logger.info(
            "pinecone query: top_k=%s ns=%s tenant=%s hits=%s",
            k,
            ns,
            (tenant_id or "-")[:8],
            len(hits),
        )
        return hits

    def delete_vectors(
        self,
        *,
        namespace: str,
        document_id: str | None = None,
        tenant_id: str | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Delete vectors for a document or by ids inside a company namespace."""
        ns = (namespace or "").strip() or "default"
        index = self._get_index()
        try:
            if ids:
                index.delete(ids=ids, namespace=ns)
                logger.info("pinecone delete ids=%s ns=%s", len(ids), ns)
                return
            flt: dict[str, Any] = {}
            if document_id:
                flt["document_id"] = {"$eq": str(document_id)}
            if tenant_id:
                flt["tenant_id"] = {"$eq": str(tenant_id)}
            if not flt:
                logger.warning("pinecone delete skipped: no filter/ids")
                return
            index.delete(filter=flt, namespace=ns)
            logger.info("pinecone delete filter=%s ns=%s", flt, ns)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pinecone delete failed ns=%s: %s", ns, exc)

    def ensure_index(self, dimension: int | None = None) -> dict[str, Any]:
        """Create serverless index if it does not exist (dev helper)."""
        self._require_configured()
        dim = dimension or settings.embedding_dimension
        try:
            from pinecone import Pinecone, ServerlessSpec

            pc = Pinecone(api_key=settings.pinecone_api_key)
            names: set[str] = set()
            for idx in pc.list_indexes():
                name = idx["name"] if isinstance(idx, dict) else getattr(idx, "name", None)
                if name:
                    names.add(str(name))

            if self.index_name in names:
                logger.info("Pinecone index already exists: %s", self.index_name)
                return {"status": "exists", "index": self.index_name, "dimension": dim}

            pc.create_index(
                name=self.index_name,
                dimension=dim,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=settings.pinecone_cloud,
                    region=settings.pinecone_region,
                ),
            )
            logger.info(
                "Created Pinecone index %s dim=%s cloud=%s region=%s",
                self.index_name,
                dim,
                settings.pinecone_cloud,
                settings.pinecone_region,
            )
            return {"status": "created", "index": self.index_name, "dimension": dim}
        except NotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("ensure_index failed")
            raise UpstreamError(
                f"Pinecone ensure_index failed: {exc}",
                provider="pinecone",
            ) from exc
