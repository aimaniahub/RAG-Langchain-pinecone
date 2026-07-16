"""Lightweight local reranker for better top context, fewer tokens (S1/S3).

Uses a free CrossEncoder when available; falls back to lexical+score fusion.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.models.domain import RetrievalResult
from app.models.schemas import SourceChunk

logger = get_logger("rag.reranker")


@lru_cache
def _get_cross_encoder() -> Any | None:
    if not settings.rerank_enabled:
        return None
    try:
        from sentence_transformers import CrossEncoder

        model_name = settings.rerank_model
        logger.info("Loading rerank model %s", model_name)
        return CrossEncoder(model_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CrossEncoder unavailable, using fallback rerank: %s", exc)
        return None


def _lexical_score(question: str, text: str) -> float:
    q = set(question.lower().split())
    t = set(text.lower().split())
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)


def _fallback_rerank(
    question: str,
    sources: list[SourceChunk],
    top_n: int,
) -> list[SourceChunk]:
    scored: list[tuple[float, SourceChunk]] = []
    for s in sources:
        base = float(s.score or 0.0)
        lex = _lexical_score(question, s.content)
        # Prefer lexical signal when dense scores are noisy / inverted
        combined = 0.35 * base + 0.65 * lex
        scored.append((combined, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[SourceChunk] = []
    for score, s in scored[:top_n]:
        meta = dict(s.metadata or {})
        meta["rerank_score"] = round(score, 4)
        meta["rerank"] = "fallback"
        out.append(SourceChunk(content=s.content, score=score, metadata=meta))
    return out


def rerank_sources(
    question: str,
    sources: list[SourceChunk],
    top_n: int | None = None,
) -> list[SourceChunk]:
    """Rerank candidates and keep top_n for the LLM context."""
    if not sources:
        return []
    top_n = top_n if top_n is not None else settings.return_top_n
    top_n = max(1, top_n)

    # Skip expensive rerank if single strong hit
    if (
        settings.rerank_skip_if_top_score
        and len(sources) == 1
        and (sources[0].score or 0) >= settings.rerank_skip_score
    ):
        return sources[:top_n]

    if not settings.rerank_enabled:
        return sources[:top_n]

    model = _get_cross_encoder()
    if model is None:
        return _fallback_rerank(question, sources, top_n)

    pairs = [(question, s.content) for s in sources]
    try:
        scores = model.predict(pairs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rerank predict failed, fallback: %s", exc)
        return _fallback_rerank(question, sources, top_n)

    ranked = sorted(
        zip(scores, sources, strict=True),
        key=lambda x: float(x[0]),
        reverse=True,
    )
    out: list[SourceChunk] = []
    for score, s in ranked[:top_n]:
        meta = dict(s.metadata or {})
        meta["rerank_score"] = round(float(score), 4)
        meta["rerank"] = "cross-encoder"
        meta["pinecone_score"] = s.score
        out.append(
            SourceChunk(
                content=s.content,
                score=float(score),
                metadata=meta,
            )
        )
    logger.info("reranked %s → %s with cross-encoder", len(sources), len(out))
    return out


def hits_to_sources(hits: list[RetrievalResult]) -> list[SourceChunk]:
    return [
        SourceChunk(content=h.content, score=h.score, metadata=h.metadata)
        for h in hits
        if h.content
    ]
