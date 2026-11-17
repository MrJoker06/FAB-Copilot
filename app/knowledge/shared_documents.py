"""Shared duty documents; no model settings or private-document ownership changes."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..personal_knowledge_runtime.contracts import PersonalKnowledgeError
from ..personal_knowledge_runtime.extractors import extract_sections
from ..personal_knowledge_runtime.storage import (
    MAX_OCR_IMAGE_PIXELS,
    MAX_OCR_PDF_PAGES,
    MAX_OCR_RENDERED_PIXELS,
    _safe_filename,
    _storage_path,
    _validate_file,
)
from .ocr import extract_image_result
from .ocr_quality import evaluate_observations


@contextmanager
def connection(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "documents.db", timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
            filename TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            storage_key TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
            process TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            sections_json TEXT NOT NULL DEFAULT '[]', error_code TEXT, error_message TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        with conn:
            yield conn
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def public_document(row, *, content=False, own=False, admin=False):
    item = {key: row[key] for key in ("document_id", "kind", "title", "filename", "mime_type", "size_bytes", "process", "status", "created_at", "updated_at")}
    item.update(enabled=bool(row["enabled"]), own=own)
    if own or admin:
        item.update(error_code=row["error_code"], error_message=row["error_message"])
    if admin:
        item.update(tenant_id=row["tenant_id"], user_id=row["user_id"])
    if content:
        item["sections"] = json.loads(row["sections_json"])
    return item


def create_upload(principal, filename, data, kind, title, process, *, storage_root: Path):
    filename = _safe_filename(filename)
    suffix, mime = _validate_file(filename, data)
    document_id = str(uuid.uuid4())
    key = f"files/{document_id}{suffix}"
    path = _storage_path(key, storage_root=storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    timestamp = now()
    try:
        with connection(storage_root) as conn:
            conn.execute("""INSERT INTO documents(document_id,kind,title,filename,mime_type,size_bytes,
                storage_key,tenant_id,user_id,process,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,'processing',?,?)""",
                (document_id,kind,title or Path(filename).stem,filename,mime,len(data),key,
                 principal.tenant_id,principal.user_id,process,timestamp,timestamp))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return document_id


def process_document(document_id, *, storage_root: Path):
    with connection(storage_root) as conn:
        row = conn.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    if row is None:
        return
    try:
        path = _storage_path(row["storage_key"], storage_root=storage_root)
        sections = extract_sections(path, path.suffix.lower(), row["title"],
            max_pdf_pages=MAX_OCR_PDF_PAGES, max_image_pixels=MAX_OCR_IMAGE_PIXELS,
            max_rendered_pixels=MAX_OCR_RENDERED_PIXELS, extract_image_result=extract_image_result)
        decision = evaluate_observations(section.ocr_observation for section in sections if section.ocr_observation)
        if not decision.accepted:
            raise PersonalKnowledgeError(422, "OCR_QUALITY_LOW", "OCR 识别质量不足，请上传更清晰的资料")
        values = [{"title": section.section_path or row["title"], "text": section.content, "page_number": section.page_number} for section in sections if section.content.strip()]
        if not values:
            raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "文件中没有可读取的文本")
        with connection(storage_root) as conn:
            conn.execute("UPDATE documents SET status='ready',sections_json=?,error_code=NULL,error_message=NULL,updated_at=? WHERE document_id=?",
                (json.dumps(values,ensure_ascii=False),now(),document_id))
    except Exception as exc:  # noqa: BLE001 - persist a sanitized failure from any file parser
        code = exc.error_code if isinstance(exc, PersonalKnowledgeError) else "DOCUMENT_PROCESSING_FAILED"
        message = exc.detail if isinstance(exc, PersonalKnowledgeError) else "资料处理失败，请管理员检查文件或重试"
        with connection(storage_root) as conn:
            conn.execute("UPDATE documents SET status='failed',error_code=?,error_message=?,updated_at=? WHERE document_id=?", (code,message,now(),document_id))


def list_documents(principal=None, *, storage_root: Path, admin=False):
    with connection(storage_root) as conn:
        rows = conn.execute("SELECT document_id,kind,title,filename,mime_type,size_bytes,tenant_id,user_id,process,status,enabled,error_code,error_message,created_at,updated_at FROM documents ORDER BY updated_at DESC,document_id DESC").fetchall()
    result = []
    for row in rows:
        own = principal is not None and row["tenant_id"] == principal.tenant_id and row["user_id"] == principal.user_id
        if admin or own or (row["status"] == "ready" and row["enabled"]):
            result.append(public_document(row, own=own, admin=admin))
    return result


def get_document(document_id, principal=None, *, storage_root: Path, admin=False, content=True):
    with connection(storage_root) as conn:
        row = conn.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    own = row is not None and principal is not None and row["tenant_id"] == principal.tenant_id and row["user_id"] == principal.user_id
    # A disabled document is withheld from user content/download routes, including its uploader.
    if row is None or not admin and (not row["enabled"] or row["status"] != "ready" and not own):
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "共享资料不存在或已停用")
    return public_document(row, content=content, own=own, admin=admin), row


def update_document(document_id, changes, *, storage_root: Path):
    with connection(storage_root) as conn:
        row = conn.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
        if row is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "共享资料不存在")
        values = {key: changes.get(key, row[key]) for key in ("title", "kind", "process", "enabled")}
        conn.execute("UPDATE documents SET title=?,kind=?,process=?,enabled=?,updated_at=? WHERE document_id=?",
            (values["title"],values["kind"],values["process"],int(values["enabled"]),now(),document_id))
    return get_document(document_id, storage_root=storage_root, admin=True)[0]


def document_file(document_id, principal=None, *, storage_root: Path, admin=False):
    _, row = get_document(document_id, principal, storage_root=storage_root, admin=admin, content=False)
    path = _storage_path(row["storage_key"], storage_root=storage_root)
    if not path.is_file():
        raise PersonalKnowledgeError(404, "DOCUMENT_FILE_MISSING", "原始文件暂不可用")
    return path, row["filename"], row["mime_type"]


def request_retry(document_id, *, storage_root: Path):
    with connection(storage_root) as conn:
        changed = conn.execute("UPDATE documents SET status='processing',error_code=NULL,error_message=NULL,updated_at=? WHERE document_id=? AND status='failed'", (now(),document_id)).rowcount
        if not changed:
            raise PersonalKnowledgeError(409, "DOCUMENT_RETRY_UNAVAILABLE", "只有处理失败的资料可以重试")


def resume_pending(*, storage_root: Path):
    # Do not create a store merely because an existing application starts.
    if not (storage_root / "documents.db").is_file():
        return
    with connection(storage_root) as conn:
        pending = [row[0] for row in conn.execute("SELECT document_id FROM documents WHERE status='processing'")]
    for document_id in pending:
        process_document(document_id, storage_root=storage_root)
