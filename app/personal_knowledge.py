from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from .audit import emit
from .config import get_settings
from .database import db_session
from .ocr import extract_image_result
from .ocr_quality import POLICY_VERSION, evaluate_observations
from .personal_knowledge_runtime import ingestion as _ingestion
from .personal_knowledge_runtime import jobs as _jobs
from .personal_knowledge_runtime.contracts import (
    ExtractedSection,
    PersonalDocumentMetadata,
    PersonalDocumentPatch,
    PersonalKnowledgeError,
)
from .personal_knowledge_runtime.extractors import extract_sections as _runtime_extract_sections
from .personal_knowledge_runtime.extractors.text import text_sections as _extractor_text_sections
from .personal_knowledge_runtime import metadata as _metadata
from .personal_knowledge_runtime.metadata import (
    _automatic_tags,
    _document_dict,
    _json_list,
    _normalise_tags,
    parse_metadata,
)
from .personal_knowledge_runtime import storage as _storage
from .processes import process_query_terms


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
    raw = json.dumps([updated_at, document_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
            raise ValueError
        return value[0], value[1]
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PersonalKnowledgeError(400, "INVALID_CURSOR", "分页游标无效") from exc


def list_personal_documents(
    owner_user_id: str,
    query: str = "",
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    clauses = ["owner_user_id = ?"]
    params: list[object] = [owner_user_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if query.strip():
        clauses.append("""(title LIKE ? OR filename LIKE ?
            OR EXISTS (SELECT 1 FROM json_each(tags_json) value WHERE value.value LIKE ?)
            OR EXISTS (SELECT 1 FROM json_each(process_steps_json) value WHERE value.value LIKE ?)
            OR EXISTS (SELECT 1 FROM json_each(equipment_ids_json) value WHERE value.value LIKE ?))""")
        value = f"%{query.strip()}%"
        params.extend([value, value, value, value, value])
    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        clauses.append("(updated_at < ? OR (updated_at = ? AND document_id < ?))")
        params.extend([cursor_time, cursor_time, cursor_id])
    bounded = max(1, min(limit, 100))
    params.append(bounded + 1)
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT d.*, (SELECT COUNT(*) FROM personal_knowledge_chunks c
                              WHERE c.document_id = d.document_id) AS chunk_count
                 FROM personal_knowledge_documents d
                 WHERE {' AND '.join(clauses)}
                 ORDER BY updated_at DESC, document_id DESC LIMIT ?""",
            params,
        ).fetchall()
    has_more = len(rows) > bounded
    selected = rows[:bounded]
    return {
        "items": [_document_dict(row) for row in selected],
        "next_cursor": _encode_cursor(selected[-1]["updated_at"], selected[-1]["document_id"]) if has_more else None,
    }


def get_personal_document(document_id: str, owner_user_id: str, include_chunks: bool = False) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM personal_knowledge_chunks c
                              WHERE c.document_id = d.document_id) AS chunk_count
               FROM personal_knowledge_documents d
               WHERE d.document_id = ? AND d.owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        result = _document_dict(row)
        if include_chunks and row["status"] == "deleting":
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        job = _latest_job(connection, document_id, owner_user_id)
        result["latest_job"] = _job_dict(job) if job else None
        if include_chunks:
            chunks = connection.execute(
                """SELECT chunk_id, page_number, section_path, chunk_index, content, token_count
                   FROM personal_knowledge_chunks
                   WHERE document_id = ? AND owner_user_id = ? ORDER BY chunk_index""",
                (document_id, owner_user_id),
            ).fetchall()
            result["chunks"] = [dict(chunk) for chunk in chunks]
    return result


def update_personal_document(document_id: str, owner_user_id: str, patch: PersonalDocumentPatch) -> dict:
    updates: dict[str, object] = {}
    fields = patch.model_fields_set
    if "title" in fields:
        updates["title"] = patch.title
    if "process_steps" in fields:
        updates["process_steps_json"] = json.dumps(patch.process_steps or [])
    if "equipment_ids" in fields:
        updates["equipment_ids_json"] = json.dumps(patch.equipment_ids or [])
    if "effective_date" in fields:
        updates["effective_date"] = patch.effective_date.isoformat() if patch.effective_date else None
    if "tags" in fields:
        updates["tags_json"] = json.dumps(_normalise_tags(patch.tags or []), ensure_ascii=False)
        updates["tags_source"] = "user"
    if not updates:
        return get_personal_document(document_id, owner_user_id)
    with db_session() as connection:
        existing = connection.execute(
            """SELECT status FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if existing is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        if existing["status"] == "deleting":
            raise PersonalKnowledgeError(409, "INVALID_DOCUMENT_STATE", "删除中的文档不能修改")
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{column} = ?" for column in updates)
        connection.execute(
            f"""UPDATE knowledge.personal_knowledge_documents SET {assignments}
                 WHERE document_id = ? AND owner_user_id = ?""",
            [*updates.values(), document_id, owner_user_id],
        )
        if "title" in updates:
            connection.execute(
                """UPDATE knowledge.personal_knowledge_fts SET title = ?
                   WHERE document_id = ? AND owner_user_id = ?""",
                (updates["title"], document_id, owner_user_id),
            )
        connection.commit()
    return get_personal_document(document_id, owner_user_id)


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
    with db_session() as connection:
        row = connection.execute(
            """SELECT filename, mime_type, storage_key, status FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
    if row is None or row["status"] == "deleting":
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
    path = _storage_path(row["storage_key"])
    if not path.exists():
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文件不存在")
    return path, row["filename"], row["mime_type"]


def _fts_query(text: str) -> str:
    terms = list(process_query_terms(text))
    for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            terms.extend(term[index:index + 3] for index in range(len(term) - 2))
        else:
            terms.append(term)
    unique = list(dict.fromkeys(term for term in terms if len(term) >= 3))[:20]
    return " OR ".join(f'"{term}"' for term in unique)


def search_personal_knowledge(
    owner_user_id: str,
    query: str,
    limit: int = 10,
    document_ids: Iterable[str] = (),
) -> list[dict]:
    bounded = max(1, min(limit, 20))
    selected_ids = list(dict.fromkeys(document_ids))[:100]
    clauses = ["f.owner_user_id = ?", "d.status = 'ready'"]
    params: list[object] = [owner_user_id]
    if selected_ids:
        placeholders = ", ".join("?" for _ in selected_ids)
        with db_session() as connection:
            owned_count = connection.execute(
                f"""SELECT COUNT(*) FROM personal_knowledge_documents
                     WHERE owner_user_id = ? AND status = 'ready' AND document_id IN ({placeholders})""",
                [owner_user_id, *selected_ids],
            ).fetchone()[0]
        if owned_count != len(selected_ids):
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "指定文档不存在或尚未完成索引")
        clauses.append(f"f.document_id IN ({placeholders})")
        params.extend(selected_ids)
    fts_query = _fts_query(query)
    normalized_query = " ".join(query.casefold().split())
    tag_terms = list(dict.fromkeys([normalized_query, *(
        term.casefold() for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", query)
    )]))[:20]
    with db_session() as connection:
        # Exact element matching prevents a tag such as "sketch" from satisfying
        # "etch". Tag matches are intentionally placed before lexical FTS results.
        if tag_terms:
            tag_clauses = ["d.owner_user_id = ?", "d.status = 'ready'"]
            tag_params: list[object] = [owner_user_id]
            if selected_ids:
                placeholders = ", ".join("?" for _ in selected_ids)
                tag_clauses.append(f"d.document_id IN ({placeholders})")
                tag_params.extend(selected_ids)
            placeholders = ", ".join("?" for _ in tag_terms)
            tag_clauses.append(
                "EXISTS (SELECT 1 FROM json_each(d.tags_json) tag "
                f"WHERE LOWER(TRIM(tag.value)) IN ({placeholders}))"
            )
            tag_params.extend(tag_terms)
            tag_params.append(bounded)
            tag_rows = connection.execute(
                f"""SELECT c.chunk_id, c.document_id, d.title, c.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number, c.content AS excerpt, -2.0 AS score
                    FROM personal_knowledge_documents d
                    JOIN personal_knowledge_chunks c ON c.chunk_id = (
                        SELECT c2.chunk_id FROM personal_knowledge_chunks c2
                        WHERE c2.document_id = d.document_id ORDER BY c2.chunk_index LIMIT 1
                    )
                    WHERE {' AND '.join(tag_clauses)}
                    ORDER BY d.updated_at DESC, d.document_id DESC LIMIT ?""",
                tag_params,
            ).fetchall()
        else:
            tag_rows = []
        if fts_query:
            rows = connection.execute(
                f"""SELECT f.chunk_id, f.document_id, f.title, f.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number,
                           snippet(personal_knowledge_fts, 2, '[', ']', '…', 32) AS excerpt,
                           round(bm25(personal_knowledge_fts), 4) AS score
                    FROM knowledge.personal_knowledge_fts f
                    JOIN personal_knowledge_chunks c ON c.chunk_id = f.chunk_id
                    JOIN personal_knowledge_documents d ON d.document_id = f.document_id
                    WHERE personal_knowledge_fts MATCH ? AND {' AND '.join(clauses)}
                    ORDER BY bm25(personal_knowledge_fts) LIMIT ?""",
                [fts_query, *params, bounded * 2],
            ).fetchall()
        else:
            fallback_clauses = ["c.owner_user_id = ?", "d.status = 'ready'", "c.content LIKE ?"]
            fallback_params: list[object] = [owner_user_id, f"%{query.strip()}%"]
            if selected_ids:
                placeholders = ", ".join("?" for _ in selected_ids)
                fallback_clauses.append(f"c.document_id IN ({placeholders})")
                fallback_params.extend(selected_ids)
            fallback_params.append(bounded * 2)
            rows = connection.execute(
                f"""SELECT c.chunk_id, c.document_id, d.title, c.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number, c.content AS excerpt, -1.0 AS score
                    FROM personal_knowledge_chunks c
                    JOIN personal_knowledge_documents d ON d.document_id = c.document_id
                    WHERE {' AND '.join(fallback_clauses)}
                    ORDER BY c.chunk_index LIMIT ?""",
                fallback_params,
            ).fetchall()
    seen_document_ids = {row["document_id"] for row in tag_rows}
    rows = list(tag_rows) + [row for row in rows if row["document_id"] not in seen_document_ids]
    rows = rows[:bounded]
    results = []
    for rank, row in enumerate(rows, start=1):
        item = dict(row)
        item["process_steps"] = _json_list(item.pop("process_steps_json", "[]"))
        item["equipment_ids"] = _json_list(item.pop("equipment_ids_json", "[]"))
        item["tags"] = _json_list(item.pop("tags_json", "[]"))
        item.update({
            "reference_id": f"PERSONAL-{item['chunk_id']}",
            "source_type": "personal",
            "source": "个人知识库",
            "section": item["section_path"],
            "retrieval": {
                "lexical_rank": rank,
                "final_score": item.pop("score"),
                "selection_reason": ["当前用户个人知识", f"lexical rank {rank}"],
            },
        })
        results.append(item)
    return results


def get_personal_chunk(chunk_id: str, owner_user_id: str) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT c.chunk_id, c.document_id, d.title, d.filename, c.page_number,
                      c.section_path, c.chunk_index, c.content, c.token_count
               FROM personal_knowledge_chunks c
               JOIN personal_knowledge_documents d ON d.document_id = c.document_id
               WHERE c.chunk_id = ? AND c.owner_user_id = ? AND d.status = 'ready'""",
            (chunk_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识章节不存在")
    return dict(row)


def pending_personal_jobs() -> list[tuple[str, str, str, str]]:
    return _jobs.pending_jobs(db_session)
