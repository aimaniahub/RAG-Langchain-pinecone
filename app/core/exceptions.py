"""Application-level exception types mapped to HTTP in the API layer."""


class AppError(Exception):
    """Base error for the company RAG application."""

    def __init__(self, message: str = "Application error") -> None:
        self.message = message
        super().__init__(message)


class NotConfiguredError(AppError):
    """Raised when a required integration is missing."""

    def __init__(self, service: str) -> None:
        super().__init__(f"{service} is not configured. Set the required env vars.")
        self.service = service


class IngestError(AppError):
    """Raised when document ingestion fails."""


class QueryError(AppError):
    """Raised when RAG query / generation fails."""


class UpstreamError(AppError):
    """Raised when OpenRouter or Pinecone (or similar) fails."""

    def __init__(self, message: str, provider: str = "upstream") -> None:
        super().__init__(message)
        self.provider = provider
