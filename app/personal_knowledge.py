from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from .audit import emit
from .config import get_settings
from .persistence.database import db_session
from .ocr import extract_image_result
from .ocr_quality import POLICY_VERSION, evaluate_observations
from .personal_knowledge_runtime import documents as _documents
from .personal_knowledge_runtime import ingestion as _ingestion
from .personal_knowledge_runtime import jobs as _jobs
from .personal_knowledge_runtime import metadata as _metadata
from .personal_knowledge_runtime import search as _search
from .personal_knowledge_runtime import storage as _storage
from .personal_knowledge_runtime.contracts import (
    ExtractedSection,
    PersonalDocumentMetadata,  # noqa: F401 - public facade compatibility
    PersonalDocumentPatch,
    PersonalKnowledgeError,  # noqa: F401 - public facade compatibility
)
from .personal_knowledge_runtime.extractors import (
    extract_sections as _runtime_extract_sections,
)
from .personal_knowledge_runtime.extractors.text import (
    text_sections as _extractor_text_sections,
)
from .personal_knowledge_runtime.metadata import (
    _automatic_tags,
    _document_dict,
    _json_list,
    _normalise_tags,
    parse_metadata,
)
from .manufacturing.processes import process_query_terms

PARSER_VERSION = "personal-v2-ocr"
SUPPORTED_SUFFIXES = _storage.SUPPORTED_SUFFIXES
MIME_TYPES = _storage.MIME_TYPES
IMAGE_FORMATS = _storage.IMAGE_FORMATS
MAX_OCR_PDF_PAGES = _storage.MAX_OCR_PDF_PAGES
MAX_OCR_IMAGE_PIXELS = _storage.MAX_OCR_IMAGE_PIXELS
MAX_OCR_RENDERED_PIXELS = _storage.MAX_OCR_RENDERED_PIXELS
MIN_NATIVE_PDF_TEXT = 20
DOCUMENT_TYPE_TAGS = _metadata.DOCUMENT_TYPE_TAGS
TOPIC_TAGS = _metadata.TOPIC_TAGS
MAX_TAG_SOURCE_CHARS = _metadata.MAX_TAG_SOURCE_CHARS


def _ingestion_dependencies() -> SimpleNamespace:
    """Resolve facade globals at call time so tests and integrations may patch them."""
    return SimpleNamespace(
        db_session=db_session,
        get_settings=get_settings,
        safe_filename=_safe_filename,
        validate_file=_validate_file,
        parse_metadata=parse_metadata,
        normalise_tags=_normalise_tags,
        initial_upload_job=_initial_upload_job,
        latest_job=_latest_job,
        storage_path=_storage_path,
        now=_now,
        emit=emit,
        parser_version=PARSER_VERSION,
        update_progress=_update_progress,
        extract_sections=_extract_sections,
        evaluate_observations=evaluate_observations,
        policy_version=POLICY_VERSION,
        automatic_tags=_automatic_tags,
        mark_failed=_mark_failed,
    )


def _document_dependencies() -> SimpleNamespace:
    """Resolve facade globals at call time for legacy patch paths."""
    return SimpleNamespace(
        db_session=db_session,
        now=_now,
        encode_cursor=_encode_cursor,
        decode_cursor=_decode_cursor,
        normalise_tags=_normalise_tags,
        document_dict=_document_dict,
        latest_job=_latest_job,
        job_dict=_job_dict,
        get_document=get_personal_document,
        storage_path=_storage_path,
    )


def _search_dependencies() -> SimpleNamespace:
    """Resolve facade globals at call time for legacy patch paths."""
    return SimpleNamespace(db_session=db_session, fts_query=_fts_query, json_list=_json_list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_filename(filename: str | None) -> str:
    return _storage._safe_filename(filename)


def _validate_file(filename: str, data: bytes) -> tuple[str, str]:
    return _storage._validate_file(
        filename, data,
        max_ocr_pdf_pages=MAX_OCR_PDF_PAGES,
        max_ocr_image_pixels=MAX_OCR_IMAGE_PIXELS,
        max_ocr_rendered_pixels=MAX_OCR_RENDERED_PIXELS,
    )


def _storage_path(storage_key: str) -> Path:
    return _storage._storage_path(storage_key, storage_root=get_settings().personal_knowledge_storage_path)


def _latest_job(connection, document_id: str, owner_user_id: str):
    return _jobs.latest_job(connection, document_id, owner_user_id)


def _initial_upload_job(connection, document_id: str, owner_user_id: str):
    """Return the immutable first upload attempt for an idempotent replay."""
    return _jobs.initial_upload_job(connection, document_id, owner_user_id)


def _job_dict(row) -> dict:
    return _jobs.job_dict(row)


def create_personal_upload(
    owner_user_id: str,
    filename: str | None,
    data: bytes,
    metadata_raw: str | None,
    idempotency_key: str,
) -> dict:
    return _ingestion.create_upload(
        _ingestion_dependencies(),
        owner_user_id,
        filename,
        data,
        metadata_raw,
        idempotency_key,
    )


def _upload_response(document, job) -> dict:
    return _ingestion.upload_response(document, job)


def _update_progress(
    document_id: str,
    owner_user_id: str,
    job_id: str,
    status: str,
    stage: str,
    progress: int,
) -> None:
    _jobs.update_progress(
        db_session,
        document_id,
        owner_user_id,
        job_id,
        status,
        stage,
        progress,
        now=_now,
    )


def _mark_failed(
    document_id: str,
    owner_user_id: str,
    job_id: str,
    error_code: str,
    detail: str,
    retryable: bool,
) -> None:
    _jobs.mark_failed(
        db_session,
        document_id,
        owner_user_id,
        job_id,
        error_code,
        detail,
        retryable,
        now=_now,
    )


def _text_sections(text: str, default_title: str, markdown: bool = False) -> list[ExtractedSection]:
    return _extractor_text_sections(text, default_title, markdown)


def _extract_sections(path: Path, suffix: str, title: str) -> list[ExtractedSection]:
    return _runtime_extract_sections(
        path,
        suffix,
        title,
        max_pdf_pages=MAX_OCR_PDF_PAGES,
        min_native_pdf_text=MIN_NATIVE_PDF_TEXT,
        max_image_pixels=MAX_OCR_IMAGE_PIXELS,
        max_rendered_pixels=MAX_OCR_RENDERED_PIXELS,
        extract_image_result=extract_image_result,
    )


def _split_content(content: str, max_chars: int = 2600, overlap_chars: int = 260) -> list[str]:
    return _ingestion.split_content(content, max_chars, overlap_chars)


def process_personal_document(document_id: str, owner_user_id: str, job_id: str) -> None:
    _ingestion.process_document(_ingestion_dependencies(), document_id, owner_user_id, job_id)


def get_personal_job(job_id: str, owner_user_id: str) -> dict:
    return _jobs.get_job(db_session, job_id, owner_user_id)


def list_personal_job_snapshots(owner_user_id: str, limit: int = 100) -> list[dict]:
    return _jobs.list_job_snapshots(db_session, owner_user_id, limit)


def _encode_cursor(updated_at: str, document_id: str) -> str:
    return _documents.encode_cursor(updated_at, document_id)


def _decode_cursor(cursor: str) -> tuple[str, str]:
    return _documents.decode_cursor(cursor)


def list_personal_documents(
    owner_user_id: str,
    query: str = "",
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    return _documents.list_documents(_document_dependencies(), owner_user_id, query, status, limit, cursor)


def get_personal_document(document_id: str, owner_user_id: str, include_chunks: bool = False) -> dict:
    return _documents.get_document(_document_dependencies(), document_id, owner_user_id, include_chunks)


def update_personal_document(document_id: str, owner_user_id: str, patch: PersonalDocumentPatch) -> dict:
    return _documents.update_document(_document_dependencies(), document_id, owner_user_id, patch)


def retry_personal_document(document_id: str, owner_user_id: str) -> dict:
    return _jobs.retry_document(db_session, document_id, owner_user_id, now=_now)


def begin_delete_personal_document(document_id: str, owner_user_id: str) -> dict:
    return _jobs.begin_delete(db_session, document_id, owner_user_id, now=_now)


def process_personal_document_deletion(document_id: str, owner_user_id: str, job_id: str) -> None:
    _jobs.process_deletion(
        db_session,
        _storage_path,
        emit,
        document_id,
        owner_user_id,
        job_id,
        now=_now,
    )


def personal_document_file(document_id: str, owner_user_id: str) -> tuple[Path, str, str]:
    return _documents.document_file(_document_dependencies(), document_id, owner_user_id)


def _fts_query(text: str) -> str:
    return _search.fts_query(text, process_query_terms)


def search_personal_knowledge(
    owner_user_id: str,
    query: str,
    limit: int = 10,
    document_ids: Iterable[str] = (),
) -> list[dict]:
    return _search.search_knowledge(_search_dependencies(), owner_user_id, query, limit, document_ids)


def get_personal_chunk(chunk_id: str, owner_user_id: str) -> dict:
    return _search.get_chunk(_search_dependencies(), chunk_id, owner_user_id)


def pending_personal_jobs() -> list[tuple[str, str, str, str]]:
    return _jobs.pending_jobs(db_session)
