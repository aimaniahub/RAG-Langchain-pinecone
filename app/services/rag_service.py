"""RAG query orchestration with timings, cache, rerank, compress (S0/S1)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from app.config import settings
from app.core.exceptions import NotConfiguredError, QueryError
from app.core.logging import get_logger
from app.core.timing import StageTimer
from app.models.schemas import QueryRequest, QueryResponse, SourceChunk
from app.models.tenant_config import TenantRagConfig
from app.rag.chains import run_qa, stream_qa
from app.rag.context_builder import build_context, compress_sources, estimate_tokens
from app.rag.reranker import hits_to_sources, rerank_sources
from app.services.cache_service import cache_service
from app.services.embedding_service import EmbeddingService
from app.services.metrics_store import QueryMetric, metrics_store
from app.vectorstore.pinecone_client import PineconeClient

logger = get_logger("services.rag")


def _lag_stage(timings: dict[str, int]) -> str | None:
    candidates = {k: v for k, v in timings.items() if k != "total"}
    if not candidates:
        return None
    return max(candidates, key=candidates.get)  # type: ignore[arg-type]


class RAGService:
    """Answer questions using retrieval + OpenRouter LLM (optimized path)."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        pinecone_client: PineconeClient | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.pinecone_client = pinecone_client or PineconeClient()

    def warmup(self) -> None:
        """Load HF embedding model (and optional reranker) at startup."""
        if settings.warmup_embeddings:
            logger.info("Warming embedding model…")
            _ = self.embedding_service.embed_query("warmup")
            logger.info("Embedding model warm")
        if settings.rerank_enabled:
            try:
                from app.rag import reranker as reranker_mod

                reranker_mod._get_cross_encoder.cache_clear()
                _ = reranker_mod._get_cross_encoder()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reranker warmup skipped: %s", exc)

    def query(
        self,
        request: QueryRequest,
        *,
        model_override: str | None = None,
        tenant_config: TenantRagConfig | None = None,
        tenant_id: str | None = None,
    ) -> QueryResponse:
        """Full path: cache → embed → retrieve → rerank → compress → LLM.

        tenant_id + namespace isolate companies. Never omit namespace for multi-tenant.
        """
        cfg = tenant_config or TenantRagConfig()
        timer = StageTimer()
        timer.start("total")

        question = request.question.strip()
        namespace = (request.namespace or "").strip()
        if not namespace:
            raise QueryError(
                "Missing company namespace. Use a company API key (not the platform admin key)."
            )
        retrieve_k = request.top_k or cfg.effective_top_k()
        return_n = cfg.effective_return_top_n()
        include_timings = (
            settings.include_timings
            if request.include_timings is None
            else request.include_timings
        )
        llm_model = model_override or cfg.effective_model() or settings.openrouter_model
        llm_key = cfg.effective_llm_api_key()
        llm_base = cfg.effective_llm_base_url()
        cache_hit = "none"
        no_ctx = cfg.effective_no_context()
        use_answer_cache = cfg.effective_answer_cache()
        use_rerank = cfg.effective_rerank()

        if not settings.is_pinecone_configured:
            raise NotConfiguredError("Pinecone")
        if not llm_key:
            raise NotConfiguredError(
                "OpenRouter (set company LLM API key or platform OPENROUTER_API_KEY)"
            )

        logger.info(
            "query retrieve_k=%s return_n=%s model=%s ns=%s tenant=%s rerank=%s",
            retrieve_k,
            return_n,
            llm_model,
            namespace,
            (tenant_id or "-")[:8],
            use_rerank,
        )

        # ---- exact answer cache (namespace + tenant_id) ----
        if use_answer_cache:
            akey = cache_service.answer_key(
                question, namespace, retrieve_k, tenant_id=tenant_id
            )
            cached = cache_service.answer_cache.get(akey)
            if cached is not None:
                timer.stop("total")
                timings = {
                    "embed": 0,
                    "retrieve": 0,
                    "rerank": 0,
                    "context": 0,
                    "llm": 0,
                    "total": timer.stages.get("total", 0),
                }
                resp = QueryResponse(
                    status=cached.get("status", "ok"),
                    question=question,
                    answer=cached["answer"],
                    sources=[SourceChunk(**s) for s in cached.get("sources", [])],
                    phase=settings.phase,
                    model=cached.get("model") or llm_model,
                    timings_ms=timings if include_timings else None,
                    cache_hit="answer",
                    context_chars=cached.get("context_chars"),
                    context_tokens_est=cached.get("context_tokens_est"),
                    lag_stage="cache" if include_timings else None,
                )
                self._record_metric(resp, cache_hit="answer")
                return resp

        # ---- embed ----
        with timer.measure("embed"):
            vector, embed_hit = self._embed_query_with_flag(question)
        if embed_hit:
            cache_hit = "embed"

        # ---- retrieve (company namespace + tenant_id filter) ----
        with timer.measure("retrieve"):
            hits = self.pinecone_client.query(
                vector=vector,
                top_k=retrieve_k,
                namespace=namespace,
                tenant_id=tenant_id,
            )
        sources = hits_to_sources(hits)

        if not sources:
            timer.stop("total")
            timings = timer.as_dict()
            resp = QueryResponse(
                status="ok",
                question=question,
                answer=no_ctx,
                sources=[],
                phase=settings.phase,
                model=llm_model,
                timings_ms=timings if include_timings else None,
                cache_hit=cache_hit,
                context_chars=0,
                context_tokens_est=0,
                lag_stage=_lag_stage(timings) if include_timings else None,
            )
            self._record_metric(resp, cache_hit=cache_hit)
            return resp

        # ---- rerank ----
        with timer.measure("rerank"):
            if use_rerank:
                ranked = rerank_sources(question, sources, top_n=return_n)
            else:
                ranked = sources[:return_n]

        # ---- compress context ----
        with timer.measure("context"):
            compressed = compress_sources(
                ranked,
                top_n=return_n,
                min_score=cfg.effective_min_score(),
                max_chars_per_chunk=cfg.effective_max_chars_per_chunk(),
            )
            context = build_context(compressed, max_chars=cfg.effective_max_context_chars())
            ctx_chars = len(context)
            ctx_tokens = estimate_tokens(context)

        # ---- LLM (company key or platform key) ----
        with timer.measure("llm"):
            answer = run_qa(
                question=question,
                context=context,
                model=llm_model,
                system_prompt=cfg.effective_system_prompt(),
                temperature=cfg.effective_temperature(),
                no_context_message=no_ctx,
                api_key=llm_key,
                base_url=llm_base,
            )

        timer.stop("total")
        timings = timer.as_dict()

        resp = QueryResponse(
            status="ok",
            question=question,
            answer=answer,
            sources=compressed,
            phase=settings.phase,
            model=llm_model,
            timings_ms=timings if include_timings else None,
            cache_hit=cache_hit,
            context_chars=ctx_chars,
            context_tokens_est=ctx_tokens,
            lag_stage=_lag_stage(timings) if include_timings else None,
        )

        if use_answer_cache:
            cache_service.answer_cache.set(
                cache_service.answer_key(
                    question, namespace, retrieve_k, tenant_id=tenant_id
                ),
                {
                    "status": "ok",
                    "answer": answer,
                    "sources": [s.model_dump() for s in compressed],
                    "model": llm_model,
                    "context_chars": ctx_chars,
                    "context_tokens_est": ctx_tokens,
                },
            )

        self._record_metric(resp, cache_hit=cache_hit)
        logger.info(
            "query done total_ms=%s lag=%s cache=%s ctx_tokens~%s",
            timings.get("total"),
            resp.lag_stage,
            cache_hit,
            ctx_tokens,
        )
        return resp

    def stream_query(
        self,
        request: QueryRequest,
        *,
        model_override: str | None = None,
        tenant_config: TenantRagConfig | None = None,
        tenant_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield events: stage updates, tokens, final payload."""
        cfg = tenant_config or TenantRagConfig()
        timer = StageTimer()
        timer.start("total")
        question = request.question.strip()
        namespace = (request.namespace or "").strip()
        if not namespace:
            raise QueryError(
                "Missing company namespace. Use a company API key (not the platform admin key)."
            )
        retrieve_k = request.top_k or cfg.effective_top_k()
        return_n = cfg.effective_return_top_n()
        llm_model = model_override or cfg.effective_model() or settings.openrouter_model
        llm_key = cfg.effective_llm_api_key()
        llm_base = cfg.effective_llm_base_url()
        no_ctx = cfg.effective_no_context()
        use_rerank = cfg.effective_rerank()

        if not settings.is_pinecone_configured:
            raise NotConfiguredError("Pinecone")
        if not llm_key:
            raise NotConfiguredError(
                "OpenRouter (set company LLM API key or platform OPENROUTER_API_KEY)"
            )

        yield {"event": "stage", "stage": "embed", "status": "start"}
        with timer.measure("embed"):
            vector, embed_hit = self._embed_query_with_flag(question)
        yield {
            "event": "stage",
            "stage": "embed",
            "status": "done",
            "ms": timer.stages.get("embed", 0),
            "cache": embed_hit,
        }

        yield {"event": "stage", "stage": "retrieve", "status": "start"}
        with timer.measure("retrieve"):
            hits = self.pinecone_client.query(
                vector=vector,
                top_k=retrieve_k,
                namespace=namespace,
                tenant_id=tenant_id,
            )
        sources = hits_to_sources(hits)
        yield {
            "event": "stage",
            "stage": "retrieve",
            "status": "done",
            "ms": timer.stages.get("retrieve", 0),
            "hits": len(sources),
        }

        if not sources:
            timer.stop("total")
            final = QueryResponse(
                status="ok",
                question=question,
                answer=no_ctx,
                sources=[],
                phase=settings.phase,
                model=llm_model,
                timings_ms=timer.as_dict(),
                cache_hit="embed" if embed_hit else "none",
                lag_stage=_lag_stage(timer.as_dict()),
            )
            self._record_metric(final, cache_hit=final.cache_hit or "none")
            yield {"event": "final", "data": final.model_dump()}
            return

        yield {"event": "stage", "stage": "rerank", "status": "start"}
        with timer.measure("rerank"):
            if use_rerank:
                ranked = rerank_sources(question, sources, top_n=return_n)
            else:
                ranked = sources[:return_n]
        yield {
            "event": "stage",
            "stage": "rerank",
            "status": "done",
            "ms": timer.stages.get("rerank", 0),
            "kept": len(ranked),
        }

        with timer.measure("context"):
            compressed = compress_sources(
                ranked,
                top_n=return_n,
                min_score=cfg.effective_min_score(),
                max_chars_per_chunk=cfg.effective_max_chars_per_chunk(),
            )
            context = build_context(compressed, max_chars=cfg.effective_max_context_chars())
        yield {
            "event": "stage",
            "stage": "context",
            "status": "done",
            "ms": timer.stages.get("context", 0),
            "chars": len(context),
            "tokens_est": estimate_tokens(context),
        }

        yield {"event": "stage", "stage": "llm", "status": "start"}
        answer_parts: list[str] = []
        with timer.measure("llm"):
            for token in stream_qa(
                question=question,
                context=context,
                model=llm_model,
                system_prompt=cfg.effective_system_prompt(),
                temperature=cfg.effective_temperature(),
                no_context_message=no_ctx,
                api_key=llm_key,
                base_url=llm_base,
            ):
                answer_parts.append(token)
                yield {"event": "token", "text": token}
        answer = "".join(answer_parts).strip()
        timer.stop("total")
        timings = timer.as_dict()

        final = QueryResponse(
            status="ok",
            question=question,
            answer=answer,
            sources=compressed,
            phase=settings.phase,
            model=llm_model,
            timings_ms=timings,
            cache_hit="embed" if embed_hit else "none",
            context_chars=len(context),
            context_tokens_est=estimate_tokens(context),
            lag_stage=_lag_stage(timings),
        )
        self._record_metric(final, cache_hit=final.cache_hit or "none")
        yield {"event": "final", "data": final.model_dump()}

    def _embed_query_with_flag(self, question: str) -> tuple[list[float], bool]:
        if settings.embed_cache_enabled:
            key = cache_service.embed_key(question)
            cached = cache_service.embed_cache.get(key)
            if cached is not None:
                return cached, True
            vector = self.embedding_service.embed_query(question)
            cache_service.embed_cache.set(key, vector)
            return vector, False
        return self.embedding_service.embed_query(question), False

    def _record_metric(self, resp: QueryResponse, cache_hit: str) -> None:
        timings = resp.timings_ms or {}
        metrics_store.record(
            QueryMetric(
                ts=time.time(),
                question_preview=(resp.question or "")[:80],
                timings_ms=dict(timings),
                cache_hit=cache_hit,
                sources=len(resp.sources or []),
                context_chars=resp.context_chars or 0,
                model=resp.model,
                status=resp.status,
            )
        )
