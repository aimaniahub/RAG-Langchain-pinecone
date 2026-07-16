"""In-memory query latency history for the Monitor UI."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class QueryMetric:
    ts: float
    question_preview: str
    timings_ms: dict[str, int]
    cache_hit: str  # none | embed | answer
    sources: int
    context_chars: int
    model: str | None
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts))
        return d


class MetricsStore:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[QueryMetric] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def record(self, metric: QueryMetric) -> None:
        with self._lock:
            self._events.appendleft(metric)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in list(self._events)[:limit]]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
        if not events:
            return {
                "count": 0,
                "avg_ms": {},
                "p50_ms": {},
                "p95_ms": {},
                "stage_share_pct": {},
                "cache_hits": {"answer": 0, "embed": 0, "none": 0},
                "slowest_stage_counts": {},
            }

        stages = ["embed", "retrieve", "rerank", "context", "llm", "total"]
        by_stage: dict[str, list[int]] = {s: [] for s in stages}
        cache_hits = {"answer": 0, "embed": 0, "none": 0}
        slowest_counts: dict[str, int] = {}

        for e in events:
            ch = e.cache_hit if e.cache_hit in cache_hits else "none"
            cache_hits[ch] = cache_hits.get(ch, 0) + 1
            for s in stages:
                if s in e.timings_ms:
                    by_stage[s].append(int(e.timings_ms[s]))
            # lag stage excluding total
            candidates = {
                k: v
                for k, v in e.timings_ms.items()
                if k not in {"total"} and isinstance(v, (int, float))
            }
            if candidates:
                lag = max(candidates, key=candidates.get)  # type: ignore[arg-type]
                slowest_counts[lag] = slowest_counts.get(lag, 0) + 1

        def pct(vals: list[int], p: float) -> int | None:
            if not vals:
                return None
            s = sorted(vals)
            idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
            return int(s[idx])

        def avg(vals: list[int]) -> int | None:
            if not vals:
                return None
            return int(sum(vals) / len(vals))

        avg_ms = {s: avg(v) for s, v in by_stage.items() if v}
        p50 = {s: pct(v, 50) for s, v in by_stage.items() if v}
        p95 = {s: pct(v, 95) for s, v in by_stage.items() if v}

        # share of average total
        total_avg = avg_ms.get("total") or 0
        share: dict[str, float] = {}
        if total_avg > 0:
            for s in ("embed", "retrieve", "rerank", "context", "llm"):
                if s in avg_ms and avg_ms[s] is not None:
                    share[s] = round(100.0 * float(avg_ms[s]) / float(total_avg), 1)

        return {
            "count": len(events),
            "avg_ms": avg_ms,
            "p50_ms": p50,
            "p95_ms": p95,
            "stage_share_pct": share,
            "cache_hits": cache_hits,
            "slowest_stage_counts": slowest_counts,
        }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


metrics_store = MetricsStore()
