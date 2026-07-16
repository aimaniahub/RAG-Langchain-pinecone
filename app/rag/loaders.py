"""Document loaders — text, markdown, PDF (Phase 2)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.core.exceptions import IngestError
from app.core.logging import get_logger
from app.models.domain import DocumentChunk

logger = get_logger("rag.loaders")

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


def load_texts(
    texts: list[str],
    metadata: dict[str, Any] | None = None,
) -> list[DocumentChunk]:
    """Wrap raw strings as DocumentChunk objects."""
    meta = dict(metadata or {})
    docs: list[DocumentChunk] = []
    for i, text in enumerate(texts):
        content = (text or "").strip()
        if not content:
            continue
        doc_id = str(meta.get("doc_id") or uuid.uuid4())
        docs.append(
            DocumentChunk(
                content=content,
                metadata={
                    **meta,
                    "source": meta.get("source", "inline"),
                    "doc_id": f"{doc_id}_{i}" if len(texts) > 1 else doc_id,
                },
            )
        )
    logger.info("load_texts: %s document(s)", len(docs))
    return docs


def load_from_path(path: str, metadata: dict[str, Any] | None = None) -> list[DocumentChunk]:
    """Load a single file path (.txt, .md, .pdf)."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise IngestError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise IngestError(f"Not a file: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_SUFFIXES)}"
        )

    base_meta: dict[str, Any] = {
        **(metadata or {}),
        "source": str(file_path.name),
        "source_path": str(file_path),
        "doc_id": str((metadata or {}).get("doc_id") or uuid.uuid4()),
    }

    if suffix == ".pdf":
        return _load_pdf(file_path, base_meta)
    return _load_text_file(file_path, base_meta)


def load_from_paths(
    paths: list[str],
    metadata: dict[str, Any] | None = None,
) -> list[DocumentChunk]:
    """Load multiple file paths."""
    docs: list[DocumentChunk] = []
    for path in paths:
        docs.extend(load_from_path(path, metadata=metadata))
    logger.info("load_from_paths: %s path(s) → %s document(s)", len(paths), len(docs))
    return docs


def load_from_bytes(
    filename: str,
    data: bytes,
    metadata: dict[str, Any] | None = None,
) -> list[DocumentChunk]:
    """Load an uploaded file from memory (.txt, .md, .pdf)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_SUFFIXES)}"
        )

    base_meta: dict[str, Any] = {
        **(metadata or {}),
        "source": filename,
        "doc_id": str((metadata or {}).get("doc_id") or uuid.uuid4()),
    }

    if suffix == ".pdf":
        return _load_pdf_bytes(filename, data, base_meta)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(f"Could not decode {filename} as UTF-8") from exc
    content = text.strip()
    if not content:
        raise IngestError(f"Empty file: {filename}")
    return [DocumentChunk(content=content, metadata=base_meta)]


def _load_text_file(path: Path, metadata: dict[str, Any]) -> list[DocumentChunk]:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IngestError(f"Failed to read {path}: {exc}") from exc
    if not content:
        raise IngestError(f"Empty file: {path}")
    logger.info("loaded text file %s (%s chars)", path.name, len(content))
    return [DocumentChunk(content=content, metadata=metadata)]


def _load_pdf(path: Path, metadata: dict[str, Any]) -> list[DocumentChunk]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestError("pypdf is required for PDF support") from exc

    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        content = "\n\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Failed to parse PDF {path.name}: {exc}") from exc

    if not content:
        raise IngestError(
            f"No extractable text in PDF {path.name} (scanned/OCR PDFs not supported yet)"
        )
    logger.info("loaded PDF %s (%s pages with text, %s chars)", path.name, len(pages), len(content))
    return [DocumentChunk(content=content, metadata={**metadata, "page_count": len(reader.pages)})]


def _load_pdf_bytes(filename: str, data: bytes, metadata: dict[str, Any]) -> list[DocumentChunk]:
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestError("pypdf is required for PDF support") from exc

    try:
        reader = PdfReader(BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        content = "\n\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Failed to parse PDF {filename}: {exc}") from exc

    if not content:
        raise IngestError(
            f"No extractable text in PDF {filename} (scanned/OCR PDFs not supported yet)"
        )
    logger.info("loaded PDF upload %s (%s pages, %s chars)", filename, len(pages), len(content))
    return [DocumentChunk(content=content, metadata={**metadata, "page_count": len(reader.pages)})]
