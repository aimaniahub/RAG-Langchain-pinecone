"""Ingest sample_policy.md via the IngestService (requires Pinecone + HF model).

Usage:
    python scripts/ingest_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app.config import settings
    from app.models.schemas import IngestRequest
    from app.services.ingest_service import IngestService

    sample = _ROOT / "data" / "raw" / "sample_policy.md"
    if not sample.exists():
        print(f"Missing sample file: {sample}")
        return 1

    if not settings.is_pinecone_configured:
        print("ERROR: PINECONE_API_KEY is not set")
        return 1

    print(f"Ingesting {sample} with embedding model {settings.embedding_model} ...")
    service = IngestService()
    resp = service.ingest(
        IngestRequest(
            file_paths=[str(sample)],
            metadata={"source": "sample_policy", "department": "HR"},
        )
    )
    print(resp.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
