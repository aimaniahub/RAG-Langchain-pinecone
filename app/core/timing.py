"""Per-stage latency measurement (S0)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class StageTimer:
    """Collect named stage durations in milliseconds."""

    stages: dict[str, int] = field(default_factory=dict)
    _marks: dict[str, float] = field(default_factory=dict, repr=False)

    def start(self, name: str) -> None:
        self._marks[name] = time.perf_counter()

    def stop(self, name: str) -> int:
        start = self._marks.pop(name, None)
        if start is None:
            return 0
        ms = int((time.perf_counter() - start) * 1000)
        self.stages[name] = ms
        return ms

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        self.start(name)
        try:
            yield
        finally:
            self.stop(name)

    def total_ms(self) -> int:
        return int(sum(self.stages.values()))

    def as_dict(self) -> dict[str, int]:
        out = dict(self.stages)
        if out and "total" not in out:
            out["total"] = self.total_ms()
        return out

    def snapshot(self, **extra: Any) -> dict[str, Any]:
        data = self.as_dict()
        data.update(extra)
        return data
