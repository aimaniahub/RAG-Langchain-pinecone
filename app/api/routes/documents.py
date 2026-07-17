"""Client document APIs (tenant-scoped via company API key only)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError, IngestError, NotConfiguredError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_scopes
from app.db.models import Tenant
from app.db.session import get_db
from app.services.document_service import DocumentService

router = APIRouter(tags=["documents"])
logger = get_logger("api.documents")


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, NotConfiguredError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, (IngestError, AppError)):
        return HTTPException(status_code=400, detail=exc.message)
    logger.exception("document error")
    return HTTPException(status_code=500, detail="Internal server error")


def _require_company(principal: Principal) -> None:
    if not settings.auth_enabled:
        return
    if not principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Company API key required. Platform admin keys use Admin UI only. "
                "Issue a key under Admin → Companies → API keys."
            ),
        )


def _company_namespace(db: Session, principal: Principal) -> tuple[str, str]:
    """Return (tenant_id, pinecone_namespace) from DB — never trust client."""
    _require_company(principal)
    if not principal.tenant_id:
        # auth off / local
        return "", (principal.namespace or settings.pinecone_namespace or "default")
    t = db.get(Tenant, principal.tenant_id)
    if not t or t.status != "active":
        raise HTTPException(status_code=403, detail="Company missing or disabled")
    ns = (t.pinecone_namespace or "").strip()
    if not ns:
        raise HTTPException(status_code=500, detail="Company has no pinecone_namespace")
    return t.id, ns


def _doc_dict(d) -> dict:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "filename": d.filename,
        "content_type": d.content_type,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "namespace": d.namespace,
        "chunk_count": d.chunk_count,
        "vector_count": d.vector_count,
        "error": d.error,
        "uploaded_by": d.uploaded_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/documents")
def list_my_documents(
    principal: Principal = Depends(require_scopes("docs:read")),
    db: Session = Depends(get_db),
) -> dict:
    _require_company(principal)
    svc = DocumentService(db)
    items = svc.list_documents(tenant_id=principal.tenant_id)
    return {"items": [_doc_dict(d) for d in items], "count": len(items)}


@router.get("/documents/{document_id}")
def get_my_document(
    document_id: str,
    principal: Principal = Depends(require_scopes("docs:read")),
    db: Session = Depends(get_db),
) -> dict:
    _require_company(principal)
    doc = DocumentService(db).get(document_id, tenant_id=principal.tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_dict(doc)


@router.post("/documents")
async def upload_my_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    async_process: str = Form(default="false"),
    principal: Principal = Depends(require_scopes("ingest:write")),
    _: None = Depends(rate_limit_dependency("ingest")),
    db: Session = Depends(get_db),
) -> dict:
    tenant_id, ns = _company_namespace(db, principal)
    data = await file.read()
    filename = file.filename or "upload.bin"
    do_async = str(async_process).lower() in {"1", "true", "yes", "on"}
    svc = DocumentService(db)
    try:
        doc = svc.upload(
            filename=filename,
            data=data,
            content_type=file.content_type or "application/octet-stream",
            namespace=ns,
            uploaded_by=principal.key_name,
            process_now=not do_async,
            tenant_id=tenant_id or None,
        )
        if do_async:

            def _job(doc_id: str) -> None:
                from app.db.session import get_session_factory

                session = get_session_factory()()
                try:
                    DocumentService(session).process_document(doc_id)
                except Exception:  # noqa: BLE001
                    logger.exception("background ingest failed")
                finally:
                    session.close()

            background_tasks.add_task(_job, doc.id)
            doc = svc.get(doc.id) or doc
        return {
            "status": "ok",
            "document": _doc_dict(doc),
            "isolation": {
                "tenant_id": tenant_id or None,
                "pinecone_namespace": ns,
            },
        }
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.delete("/documents/{document_id}")
def delete_my_document(
    document_id: str,
    principal: Principal = Depends(require_scopes("ingest:write")),
    db: Session = Depends(get_db),
) -> dict:
    _require_company(principal)
    doc = DocumentService(db).get(document_id, tenant_id=principal.tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        DocumentService(db).delete_document(document_id)
        return {"status": "ok", "deleted": document_id}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc
