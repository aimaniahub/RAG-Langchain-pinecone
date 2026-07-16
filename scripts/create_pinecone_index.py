"""Create Pinecone serverless index if missing (dimension must match HF embeddings).

Usage (repo root, conda env active, .env set):
    python scripts/create_pinecone_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app.config import settings
    from app.vectorstore.pinecone_client import PineconeClient

    if not settings.is_pinecone_configured:
        print("ERROR: PINECONE_API_KEY is not set")
        return 1

    print(f"Index: {settings.pinecone_index_name}")
    print(f"Dimension: {settings.embedding_dimension} (HF model {settings.embedding_model})")
    print(f"Cloud/region: {settings.pinecone_cloud}/{settings.pinecone_region}")

    client = PineconeClient()
    result = client.ensure_index()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
