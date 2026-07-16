"""Context compression: score filter, dedupe, truncate (S1.6)."""

from __future__ import annotations

from app.config import settings
from app.core.logging import get_logger
from app.models.schemas import SourceChunk

logger = get_logger("rag.context")


def filter_by_min_score(sources: list[SourceChunk], min_score: float) -> list[SourceChunk]:
    if min_score <= 0:
        return list(sources)
    kept = [s for s in sources if s.score is None or s.score >= min_score]
    return kept if kept else list(sources)[:1]  # keep best if all filtered


def dedupe_sources(sources: list[SourceChunk], similarity: float = 0.9) -> list[SourceChunk]:
    """Drop near-duplicate chunks by simple token Jaccard."""
    kept: list[SourceChunk] = []
    seen_tokens: list[set[str]] = []
    for src in sources:
        tokens = set(src.content.lower().split())
        if not tokens:
            continue
        dup = False
        for prev in seen_tokens:
            inter = len(tokens & prev)
            union = len(tokens | prev) or 1
            if inter / union >= similarity:
                dup = True
                break
        if not dup:
            kept.append(src)
            seen_tokens.append(tokens)
    return kept


def truncate_chunk(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0]
    return (cut or text[:max_chars]).rstrip() + "…"


def compress_sources(
    sources: list[SourceChunk],
    top_n: int | None = None,
    min_score: float | None = None,
    max_chars_per_chunk: int | None = None,
) -> list[SourceChunk]:
    """Filter → dedupe → top_n → truncate content copies."""
    min_score = settings.min_retrieval_score if min_score is None else min_score
    top_n = settings.return_top_n if top_n is None else top_n
    max_chars = (
        settings.max_chars_per_chunk if max_chars_per_chunk is None else max_chars_per_chunk
    )

    out = filter_by_min_score(sources, min_score)
    out = dedupe_sources(out)
    if top_n > 0:
        out = out[:top_n]

    compressed: list[SourceChunk] = []
    for s in out:
        compressed.append(
            SourceChunk(
                content=truncate_chunk(s.content, max_chars),
                score=s.score,
                metadata=dict(s.metadata or {}),
            )
        )
    logger.info(
        "compress_sources in=%s out=%s top_n=%s min_score=%s max_chars=%s",
        len(sources),
        len(compressed),
        top_n,
        min_score,
        max_chars,
    )
    return compressed


def build_context(sources: list[SourceChunk], max_chars: int | None = None) -> str:
    max_chars = settings.max_context_chars if max_chars is None else max_chars
    parts: list[str] = []
    total = 0
    for i, src in enumerate(sources, start=1):
        block = f"[{i}] {src.content}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block) + 2
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token)."""
    return max(1, len(text) // 4) if text else 0
