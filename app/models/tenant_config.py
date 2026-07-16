"""Per-tenant RAG overrides (null fields fall back to platform settings)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass
class TenantRagConfig:
    system_prompt: str | None = None
    top_k: int | None = None
    return_top_n: int | None = None
    max_context_chars: int | None = None
    max_question_chars: int | None = None
    max_chars_per_chunk: int | None = None
    temperature: float | None = None
    min_retrieval_score: float | None = None
    rerank_enabled: bool | None = None
    answer_cache_enabled: bool | None = None
    no_context_message: str | None = None
    default_model: str | None = None

    @classmethod
    def from_tenant(cls, tenant: Any | None) -> TenantRagConfig:
        if tenant is None:
            return cls()
        rerank = getattr(tenant, "rerank_enabled", None)
        cache = getattr(tenant, "answer_cache_enabled", None)
        return cls(
            system_prompt=(getattr(tenant, "system_prompt", None) or None),
            top_k=getattr(tenant, "top_k", None),
            return_top_n=getattr(tenant, "return_top_n", None),
            max_context_chars=getattr(tenant, "max_context_chars", None),
            max_question_chars=getattr(tenant, "max_question_chars", None),
            max_chars_per_chunk=getattr(tenant, "max_chars_per_chunk", None),
            temperature=getattr(tenant, "temperature", None),
            min_retrieval_score=getattr(tenant, "min_retrieval_score", None),
            rerank_enabled=None if rerank is None else bool(rerank),
            answer_cache_enabled=None if cache is None else bool(cache),
            no_context_message=(getattr(tenant, "no_context_message", None) or None),
            default_model=getattr(tenant, "default_model", None),
        )

    def effective_top_k(self) -> int:
        return int(self.top_k or settings.retrieve_top_k or settings.top_k or 5)

    def effective_return_top_n(self) -> int:
        return int(self.return_top_n or settings.return_top_n or 3)

    def effective_max_context_chars(self) -> int:
        return int(self.max_context_chars or settings.max_context_chars or 4000)

    def effective_max_question_chars(self) -> int:
        return int(self.max_question_chars or settings.max_question_chars or 2000)

    def effective_max_chars_per_chunk(self) -> int:
        return int(self.max_chars_per_chunk or settings.max_chars_per_chunk or 800)

    def effective_temperature(self) -> float:
        if self.temperature is None:
            return float(settings.llm_temperature)
        return float(self.temperature)

    def effective_min_score(self) -> float:
        if self.min_retrieval_score is None:
            return float(settings.min_retrieval_score)
        return float(self.min_retrieval_score)

    def effective_rerank(self) -> bool:
        if self.rerank_enabled is None:
            return bool(settings.rerank_enabled)
        return bool(self.rerank_enabled)

    def effective_answer_cache(self) -> bool:
        if self.answer_cache_enabled is None:
            return bool(settings.answer_cache_enabled)
        return bool(self.answer_cache_enabled)

    def effective_system_prompt(self) -> str:
        if self.system_prompt and self.system_prompt.strip():
            return self.system_prompt.strip()
        from app.rag.prompts import get_system_prompt

        return get_system_prompt()

    def effective_no_context(self) -> str:
        if self.no_context_message and self.no_context_message.strip():
            return self.no_context_message.strip()
        return (
            "I could not find relevant information in the company knowledge base "
            "for this question."
        )

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "top_k": self.top_k,
            "return_top_n": self.return_top_n,
            "max_context_chars": self.max_context_chars,
            "max_question_chars": self.max_question_chars,
            "max_chars_per_chunk": self.max_chars_per_chunk,
            "temperature": self.temperature,
            "min_retrieval_score": self.min_retrieval_score,
            "rerank_enabled": self.rerank_enabled,
            "answer_cache_enabled": self.answer_cache_enabled,
            "no_context_message": self.no_context_message,
            "defaults": {
                "top_k": settings.retrieve_top_k or settings.top_k,
                "return_top_n": settings.return_top_n,
                "max_context_chars": settings.max_context_chars,
                "max_question_chars": settings.max_question_chars,
                "max_chars_per_chunk": settings.max_chars_per_chunk,
                "temperature": settings.llm_temperature,
                "min_retrieval_score": settings.min_retrieval_score,
                "rerank_enabled": settings.rerank_enabled,
                "answer_cache_enabled": settings.answer_cache_enabled,
                "default_model": settings.openrouter_model,
            },
        }
