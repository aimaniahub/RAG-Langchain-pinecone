"""Shared FastAPI dependencies (service factories)."""

from functools import lru_cache

from app.services.embedding_service import EmbeddingService
from app.services.ingest_service import IngestService
from app.services.rag_service import RAGService
from app.vectorstore.pinecone_client import PineconeClient


@lru_cache
def get_pinecone_client() -> PineconeClient:
    return PineconeClient()


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_ingest_service() -> IngestService:
    return IngestService(
        embedding_service=get_embedding_service(),
        pinecone_client=get_pinecone_client(),
    )


@lru_cache
def get_rag_service() -> RAGService:
    return RAGService(
        embedding_service=get_embedding_service(),
        pinecone_client=get_pinecone_client(),
    )
