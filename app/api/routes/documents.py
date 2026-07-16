"""Admin document upload + auto-embed routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, IngestError, NotConfiguredError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_dependency
from app.core.security import Principal, require_roles
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


def _doc_dict(d) -> dict:
    return {
        "id": d.id,
        "filename": d.filename,
        "content_type": d.content_type,
        "size_bytes": d.size_bytes,
        "storage_key": d.storage_key,
        "storage_backend": d.storage_backend,
        "status": d.status,
        "namespace": d.namespace,
        "chunk_count": d.chunk_count,
        "vector_count": d.vector_count,
        "error": d.error,
        "uploaded_by": d.uploaded_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


@router.get("/admin/documents")
def list_documents(
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    svc = DocumentService(db)
    items = [_doc_dict(d) for d in svc.list_documents()]
    return {"items": items, "count": len(items)}


@router.get("/admin/documents/{document_id}")
def get_document(
    document_id: str,
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    doc = DocumentService(db).get(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_dict(doc)


@router.post("/admin/documents")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    namespace: str | None = Form(default=None),
    async_process: str = Form(default="false"),
    principal: Principal = Depends(require_roles("admin")),
    _: None = Depends(rate_limit_dependency("ingest")),
    db: Session = Depends(get_db),
) -> dict:
    """Upload company file → storage → auto embed to Pinecone."""
    data = await file.read()
    filename = file.filename or "upload.bin"
    do_async = str(async_process).lower() in {"1", "true", "yes", "on"}
    svc = DocumentService(db)
    try:
        if do_async:
            doc = svc.upload(
                filename=filename,
                data=data,
                content_type=file.content_type or "application/octet-stream",
                namespace=namespace,
                uploaded_by=principal.key_name,
                process_now=False,
            )

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
        else:
            doc = svc.upload(
                filename=filename,
                data=data,
                content_type=file.content_type or "application/octet-stream",
                namespace=namespace,
                uploaded_by=principal.key_name,
                process_now=True,
            )
        return {"status": "ok", "document": _doc_dict(doc)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.post("/admin/documents/{document_id}/reprocess")
def reprocess_document(
    document_id: str,
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        doc = DocumentService(db).process_document(document_id)
        return {"status": "ok", "document": _doc_dict(doc)}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc


@router.delete("/admin/documents/{document_id}")
def delete_document(
    document_id: str,
    principal: Principal = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    _ = principal
    try:
        DocumentService(db).delete_document(document_id)
        return {"status": "ok", "deleted": document_id}
    except Exception as exc:  # noqa: BLE001
        raise _map(exc) from exc
