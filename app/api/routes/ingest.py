"""Document ingest routes (admin when auth enabled)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.deps import get_ingest_service
from app.config import settings
from app.core.audit import audit
from app.core.exceptions import AppError, IngestError, NotConfiguredError, UpstreamError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_roles
from app.models.schemas import IngestRequest, IngestResponse
from app.services.ingest_service import IngestService

router = APIRouter(tags=["ingest"])
logger = get_logger("api.ingest")


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotConfiguredError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, IngestError):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, UpstreamError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=500, detail=exc.message)
    logger.exception("Unhandled ingest error")
    return HTTPException(status_code=500, detail="Internal server error")


@router.post("/ingest", response_model=IngestResponse)
def ingest_documents(
    body: IngestRequest,
    request: Request,
    principal: Principal = Depends(require_roles("admin")),
    _: None = Depends(rate_limit_dependency("ingest")),
    service: IngestService = Depends(get_ingest_service),
) -> IngestResponse:
    """Ingest inline texts and/or local file paths (.txt, .md, .pdf)."""
    logger.info(
        "POST /ingest actor=%s texts=%s paths=%s",
        principal.key_name,
        len(body.texts or []),
        len(body.file_paths or []),
    )
    try:
        result = service.ingest(body)
        audit(
            "ingest.completed",
            actor=principal.key_name,
            role=principal.role,
            documents=result.documents_received,
            chunks=result.chunks_created,
            vectors=result.vectors_upserted,
            request_id=getattr(request.state, "request_id", None),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        audit(
            "ingest.failed",
            actor=principal.key_name,
            error=str(exc)[:200],
            request_id=getattr(request.state, "request_id", None),
        )
        raise _map_error(exc) from exc


@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    request: Request,
    file: UploadFile = File(..., description="Upload .txt, .md, or .pdf"),
    namespace: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
    principal: Principal = Depends(require_roles("admin")),
    _: None = Depends(rate_limit_dependency("ingest")),
    service: IngestService = Depends(get_ingest_service),
) -> IngestResponse:
    """Multipart file upload ingest."""
    filename = file.filename or "upload.bin"
    logger.info("POST /ingest/file actor=%s name=%s", principal.key_name, filename)
    meta: dict[str, Any] = {}
    if metadata_json:
        try:
            parsed = json.loads(metadata_json)
            if not isinstance(parsed, dict):
                raise ValueError("metadata_json must be a JSON object")
            meta = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid metadata_json: {exc}") from exc

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.max_upload_bytes} bytes",
        )

    try:
        result = service.ingest_file_upload(
            filename=filename,
            data=data,
            metadata=meta,
            namespace=namespace,
        )
        audit(
            "ingest.file.completed",
            actor=principal.key_name,
            filename=filename,
            vectors=result.vectors_upserted,
            request_id=getattr(request.state, "request_id", None),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc) from exc
