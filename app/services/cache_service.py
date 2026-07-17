"""In-process caches for query embeddings and answers (S1)."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Generic, TypeVar

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("services.cache")

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe LRU + TTL cache."""

    def __init__(self, max_size: int = 2048, ttl_seconds: int = 3600) -> None:
        self.max_size = max(1, max_size)
        self.ttl_seconds = max(1, ttl_seconds)
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl_seconds]
        for k in expired:
            del self._data[k]

    def get(self, key: str) -> T | None:
        with self._lock:
            self._purge_expired()
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            ts, value = item
            if time.time() - ts > self.ttl_seconds:
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: T) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def clear_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]
            return len(keys)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self.hits,
                "misses": self.misses,
            }


def normalize_question(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def make_key(*parts: str) -> str:
    raw = "||".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CacheService:
    """Embed + answer caches with namespace-aware invalidation."""

    def __init__(self) -> None:
        ttl = settings.cache_ttl_seconds
        size = settings.cache_max_size
        self.embed_cache: TTLCache[list[float]] = TTLCache(max_size=size, ttl_seconds=ttl)
        self.answer_cache: TTLCache[dict[str, Any]] = TTLCache(max_size=size, ttl_seconds=ttl)
        self._generation: dict[str, int] = {"default": 0}
        self._lock = threading.Lock()

    def generation(self, namespace: str) -> int:
        ns = namespace or "default"
        with self._lock:
            return self._generation.get(ns, 0)

    def bump_generation(self, namespace: str | None = None) -> None:
        """Call after ingest so answer caches for that namespace miss."""
        ns = namespace or settings.pinecone_namespace or "default"
        with self._lock:
            self._generation[ns] = self._generation.get(ns, 0) + 1
        # clear answer keys for ns by clearing all answers (simple + safe)
        n = self.answer_cache.clear()
        logger.info("cache invalidate namespace=%s cleared_answers=%s gen=%s", ns, n, self.generation(ns))

    def embed_key(self, question: str) -> str:
        return make_key("embed", settings.embedding_model, normalize_question(question))

    def answer_key(
        self,
        question: str,
        namespace: str | None,
        top_k: int,
        tenant_id: str | None = None,
    ) -> str:
        ns = namespace or settings.pinecone_namespace or "default"
        gen = str(self.generation(ns))
        return make_key(
            "answer",
            normalize_question(question),
            ns,
            str(tenant_id or ""),
            str(top_k),
            settings.openrouter_model,
            gen,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "embed": self.embed_cache.stats(),
            "answer": self.answer_cache.stats(),
            "generations": dict(self._generation),
        }


# process singleton
cache_service = CacheService()
