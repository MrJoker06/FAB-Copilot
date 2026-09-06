"""Upload and ingestion workflow, parameterised by facade-owned runtime hooks."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Protocol

from .contracts import PersonalKnowledgeError


class IngestionDependencies(Protocol):
    db_session: object
    get_settings: object
    safe_filename: object
    validate_file: object
    parse_metadata: object
    normalise_tags: object
    initial_upload_job: object
    latest_job: object
    storage_path: object
    now: object
    emit: object
    parser_version: str
    update_progress: object
    extract_sections: object
    evaluate_observations: object
    policy_version: str
    automatic_tags: object
    mark_failed: object


def upload_response(document, job) -> dict:
    return {
        "document_id": document["document_id"],
        "job_id": job["job_id"],
        "status": document["status"],
        "filename": document["filename"],
        "status_url": f"/api/knowledge/jobs/{job['job_id']}",
    }


def split_content(content: str, max_chars: int = 2600, overlap_chars: int = 260) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", content).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            boundary = max(normalized.rfind("\n", start + max_chars // 2, end), normalized.rfind("。", start + max_chars // 2, end))
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def create_upload(
    deps: IngestionDependencies,
    owner_user_id: str,
    filename: str | None,
    data: bytes,
    metadata_raw: str | None,
    idempotency_key: str,
) -> dict:
    db_session = deps.db_session
    get_settings = deps.get_settings
    _safe_filename = deps.safe_filename
    _validate_file = deps.validate_file
    parse_metadata = deps.parse_metadata
    _normalise_tags = deps.normalise_tags
    _initial_upload_job = deps.initial_upload_job
    _latest_job = deps.latest_job
    _upload_response = upload_response
    _storage_path = deps.storage_path
    _now = deps.now
    emit = deps.emit
    PARSER_VERSION = deps.parser_version
    settings = get_settings()
    if len(data) > settings.personal_knowledge_max_upload_bytes:
        raise PersonalKnowledgeError(413, "FILE_TOO_LARGE", "文件超过当前上传大小限制")
    safe_name = _safe_filename(filename)
    suffix, mime_type = _validate_file(safe_name, data)
    metadata = parse_metadata(metadata_raw)
    tags_source = "user" if "tags" in metadata.model_fields_set else "auto"
    checksum = hashlib.sha256(data).hexdigest()

    with db_session() as connection:
        idempotent = connection.execute(
            """SELECT * FROM personal_knowledge_documents
               WHERE owner_user_id = ? AND idempotency_key = ?""",
            (owner_user_id, idempotency_key),
        ).fetchone()
        if idempotent is not None:
            if idempotent["checksum_sha256"] != checksum:
                raise PersonalKnowledgeError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同文件")
            # A replay identifies the original upload transaction, not a later
            # retry.  Document detail continues to expose the latest job.
            job = _initial_upload_job(connection, idempotent["document_id"], owner_user_id)
            response = _upload_response(idempotent, job)
            response["_start_processing"] = False
            return response
        duplicate = connection.execute(
            """SELECT document_id FROM personal_knowledge_documents
               WHERE owner_user_id = ? AND checksum_sha256 = ?""",
            (owner_user_id, checksum),
        ).fetchone()
        if duplicate is not None:
            raise PersonalKnowledgeError(409, "DUPLICATE_DOCUMENT", "当前个人知识库已存在完全相同的文件")

    document_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    owner_directory = hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:24]
    storage_key = f"{owner_directory}/{document_id}/original{suffix}"
    target = _storage_path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(target)
    timestamp = _now()
    title = metadata.title or Path(safe_name).stem[:200] or "未命名文档"
    try:
        with db_session() as connection:
            connection.execute(
                """INSERT INTO knowledge.personal_knowledge_documents(
                       document_id, owner_user_id, filename, title, mime_type, size_bytes,
                       checksum_sha256, process_steps_json, equipment_ids_json, effective_date,
                       tags_json, tags_source, status, storage_key, parser_version, idempotency_key,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?, ?, ?, ?)""",
                (
                    document_id, owner_user_id, safe_name, title, mime_type, len(data), checksum,
                    json.dumps(metadata.process_steps), json.dumps(metadata.equipment_ids),
                    metadata.effective_date.isoformat() if metadata.effective_date else None,
                    json.dumps(_normalise_tags(metadata.tags), ensure_ascii=False), tags_source, storage_key, PARSER_VERSION,
                    idempotency_key, timestamp, timestamp,
                ),
            )
            connection.execute(
                """INSERT INTO knowledge.personal_knowledge_jobs(
                       job_id, document_id, owner_user_id, status, stage, progress, attempt,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, 'uploaded', 'queued', 0, 1, ?, ?)""",
                (job_id, document_id, owner_user_id, timestamp, timestamp),
            )
            connection.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise

    emit(
        "personal_knowledge_uploaded",
        job_id,
        status="success",
        document_id=document_id,
        owner_fingerprint=hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:12],
        filename_suffix=suffix,
        size_bytes=len(data),
    )
    with db_session() as connection:
        document = connection.execute(
            "SELECT * FROM personal_knowledge_documents WHERE document_id = ?", (document_id,)
        ).fetchone()
        job = _latest_job(connection, document_id, owner_user_id)
    response = _upload_response(document, job)
    response["_start_processing"] = True
    return response


def process_document(
    deps: IngestionDependencies,
    document_id: str,
    owner_user_id: str,
    job_id: str,
) -> None:
    db_session = deps.db_session
    _update_progress = deps.update_progress
    _storage_path = deps.storage_path
    _extract_sections = deps.extract_sections
    evaluate_observations = deps.evaluate_observations
    POLICY_VERSION = deps.policy_version
    emit = deps.emit
    _automatic_tags = deps.automatic_tags
    _split_content = split_content
    _now = deps.now
    _mark_failed = deps.mark_failed
    try:
        _update_progress(document_id, owner_user_id, job_id, "parsing", "extracting_text", 10)
        with db_session() as connection:
            document = connection.execute(
                """SELECT * FROM personal_knowledge_documents
                   WHERE document_id = ? AND owner_user_id = ?""",
                (document_id, owner_user_id),
            ).fetchone()
        if document is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        path = _storage_path(document["storage_key"])
        if not path.exists():
            raise PersonalKnowledgeError(500, "STORAGE_FILE_MISSING", "原始文件不存在", True)
        sections = _extract_sections(path, path.suffix.lower(), document["title"])
        observations = [
            section.ocr_observation
            for section in sections
            if section.ocr_observation
        ]
        decision = evaluate_observations(observations)
        if observations:
            emit(
                "personal_knowledge_ocr_quality",
                job_id,
                status="success" if decision.accepted else "rejected",
                policy_version=POLICY_VERSION,
                categories=sorted({item.category for item in observations}),
                ocr_pages=decision.ocr_pages,
                recognized_pages=decision.recognized_pages,
                mean_confidence=decision.mean_confidence,
                low_confidence_ratio=decision.low_confidence_ratio,
                reason=decision.reason,
            )
        if not decision.accepted:
            raise PersonalKnowledgeError(422, "OCR_QUALITY_LOW", "OCR 识别质量不足，未写入知识库", False)
        automatic_tags = _automatic_tags(document["title"], document["filename"], sections)
        _update_progress(document_id, owner_user_id, job_id, "chunking", "chunking", 45)
        chunks: list[tuple[int | None, str, str]] = []
        for section in sections:
            chunks.extend(
                (section.page_number, section.section_path, content)
                for content in _split_content(section.content)
            )
        if not chunks:
            raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "文件中没有可索引文本")
        _update_progress(document_id, owner_user_id, job_id, "indexing", "full_text_index", 75)
        timestamp = _now()
        with db_session() as connection:
            connection.execute(
                "DELETE FROM knowledge.personal_knowledge_fts WHERE document_id = ?", (document_id,)
            )
            connection.execute(
                "DELETE FROM knowledge.personal_knowledge_chunks WHERE document_id = ?", (document_id,)
            )
            for index, (page_number, section_path, content) in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                cursor = connection.execute(
                    """INSERT INTO knowledge.personal_knowledge_chunks(
                           chunk_id, document_id, owner_user_id, page_number, section_path,
                           chunk_index, content, token_count, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id, document_id, owner_user_id, page_number, section_path,
                        index, content, max(1, len(content) // 2), timestamp,
                    ),
                )
                connection.execute(
                    """INSERT INTO knowledge.personal_knowledge_fts(
                           rowid, title, section_path, content, owner_user_id, document_id, chunk_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (cursor.lastrowid, document["title"], section_path, content, owner_user_id, document_id, chunk_id),
                )
            connection.execute(
                """UPDATE knowledge.personal_knowledge_documents
                   SET status = 'ready', error_code = NULL, error_message = NULL,
                       tags_json = CASE WHEN tags_source = 'auto' THEN ? ELSE tags_json END,
                       updated_at = ?
                   WHERE document_id = ? AND owner_user_id = ?""",
                (json.dumps(automatic_tags, ensure_ascii=False), timestamp, document_id, owner_user_id),
            )
            connection.execute(
                """UPDATE knowledge.personal_knowledge_jobs
                   SET status = 'ready', stage = 'ready', progress = 100, error_code = NULL,
                       error_message = NULL, retryable = 0, updated_at = ?
                   WHERE job_id = ? AND owner_user_id = ?""",
                (timestamp, job_id, owner_user_id),
            )
            connection.commit()
        emit(
            "personal_knowledge_ingestion_finished",
            job_id,
            status="success",
            document_id=document_id,
            chunks=len(chunks),
        )
    except PersonalKnowledgeError as exc:
        _mark_failed(document_id, owner_user_id, job_id, exc.error_code, exc.detail, exc.retryable)
        emit("personal_knowledge_ingestion_finished", job_id, status="error", document_id=document_id, error_code=exc.error_code)
    except Exception as exc:
        _mark_failed(document_id, owner_user_id, job_id, "INGESTION_FAILED", "文档解析或索引失败", True)
        emit(
            "personal_knowledge_ingestion_finished",
            job_id,
            status="error",
            document_id=document_id,
            error_code="INGESTION_FAILED",
            error_type=type(exc).__name__,
        )
