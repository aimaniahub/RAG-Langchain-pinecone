"""HTTP request/response schemas — Phase 3 + S0/S1 speed fields."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    phase: int = 4
    app_name: str = "company-rag"
    detail: str = "Production RAG"


class ReadyResponse(BaseModel):
    status: str  # ready | not_ready
    phase: int = 4
    app_name: str = "company-rag"
    auth_enabled: bool = False
    openrouter_configured: bool = False
    pinecone_configured: bool = False
    embedding_model: str = ""
    index_name: str = ""
    detail: str = ""
    speed_features: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
    detail: str | None = None
    request_id: str | None = None


class IngestRequest(BaseModel):
    texts: list[str] = Field(default_factory=list, description="Inline document texts")
    file_paths: list[str] = Field(
        default_factory=list,
        description="Local paths to .txt, .md, or .pdf files",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    namespace: str | None = Field(
        default=None,
        description="Optional Pinecone namespace override",
    )


class IngestResponse(BaseModel):
    status: str
    message: str
    documents_received: int = 0
    chunks_created: int = 0
    vectors_upserted: int = 0
    namespace: str = "default"
    phase: int = 3


class SourceChunk(BaseModel):
    content: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    namespace: str | None = None
    include_timings: bool | None = Field(
        default=None,
        description="Include per-stage timings_ms (default: server setting)",
    )


class QueryResponse(BaseModel):
    status: str
    question: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    phase: int = 3
    model: str | None = None
    timings_ms: dict[str, int] | None = None
    cache_hit: str | None = None  # none | embed | answer
    context_chars: int | None = None
    context_tokens_est: int | None = None
    lag_stage: str | None = None


class MetricsSummaryResponse(BaseModel):
    count: int
    avg_ms: dict[str, Any] = Field(default_factory=dict)
    p50_ms: dict[str, Any] = Field(default_factory=dict)
    p95_ms: dict[str, Any] = Field(default_factory=dict)
    stage_share_pct: dict[str, Any] = Field(default_factory=dict)
    cache_hits: dict[str, Any] = Field(default_factory=dict)
    slowest_stage_counts: dict[str, Any] = Field(default_factory=dict)
    cache_stats: dict[str, Any] = Field(default_factory=dict)
