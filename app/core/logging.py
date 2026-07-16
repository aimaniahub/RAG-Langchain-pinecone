"""Logging setup — text (dev) or JSON (prod)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int | None = None, log_format: str = "text") -> logging.Logger:
    """Configure root app logger and return the application logger."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    resolved = level if level is not None else logging.INFO
    root.addHandler(handler)
    root.setLevel(resolved)

    logger = logging.getLogger("app")
    logger.setLevel(resolved)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"app.{name}" if not name.startswith("app") else name)
