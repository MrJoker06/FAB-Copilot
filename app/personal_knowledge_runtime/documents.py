"""Document query and mutation operations for personal knowledge."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Protocol

from .contracts import PersonalDocumentPatch, PersonalKnowledgeError


class DocumentDependencies(Protocol):
    db_session: object
    now: object
    encode_cursor: object
    decode_cursor: object
    normalise_tags: object
    document_dict: object
    latest_job: object
    job_dict: object
    get_document: object
    storage_path: object


def encode_cursor(updated_at: str, document_id: str) -> str:
    raw = json.dumps([updated_at, document_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
            raise ValueError
        return value[0], value[1]
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PersonalKnowledgeError(400, "INVALID_CURSOR", "分页游标无效") from exc


def list_documents(
    deps: DocumentDependencies,
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
        cursor_time, cursor_id = deps.decode_cursor(cursor)
        clauses.append("(updated_at < ? OR (updated_at = ? AND document_id < ?))")
        params.extend([cursor_time, cursor_time, cursor_id])
    bounded = max(1, min(limit, 100))
    params.append(bounded + 1)
    with deps.db_session() as connection:
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
        "items": [deps.document_dict(row) for row in selected],
        "next_cursor": deps.encode_cursor(selected[-1]["updated_at"], selected[-1]["document_id"]) if has_more else None,
    }


def get_document(
    deps: DocumentDependencies, document_id: str, owner_user_id: str, include_chunks: bool = False
) -> dict:
    with deps.db_session() as connection:
        row = connection.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM personal_knowledge_chunks c
                              WHERE c.document_id = d.document_id) AS chunk_count
               FROM personal_knowledge_documents d
               WHERE d.document_id = ? AND d.owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        result = deps.document_dict(row)
        if include_chunks and row["status"] == "deleting":
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        job = deps.latest_job(connection, document_id, owner_user_id)
        result["latest_job"] = deps.job_dict(job) if job else None
        if include_chunks:
            chunks = connection.execute(
                """SELECT chunk_id, page_number, section_path, chunk_index, content, token_count
                   FROM personal_knowledge_chunks
                   WHERE document_id = ? AND owner_user_id = ? ORDER BY chunk_index""",
                (document_id, owner_user_id),
            ).fetchall()
            result["chunks"] = [dict(chunk) for chunk in chunks]
    return result


def update_document(
    deps: DocumentDependencies, document_id: str, owner_user_id: str, patch: PersonalDocumentPatch
) -> dict:
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
        updates["tags_json"] = json.dumps(deps.normalise_tags(patch.tags or []), ensure_ascii=False)
        updates["tags_source"] = "user"
    if not updates:
        return deps.get_document(document_id, owner_user_id)
    with deps.db_session() as connection:
        existing = connection.execute(
            """SELECT status FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if existing is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        if existing["status"] == "deleting":
            raise PersonalKnowledgeError(409, "INVALID_DOCUMENT_STATE", "删除中的文档不能修改")
        updates["updated_at"] = deps.now()
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
    return deps.get_document(document_id, owner_user_id)


def document_file(deps: DocumentDependencies, document_id: str, owner_user_id: str) -> tuple[Path, str, str]:
    with deps.db_session() as connection:
        row = connection.execute(
            """SELECT filename, mime_type, storage_key, status FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
    if row is None or row["status"] == "deleting":
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
    path = deps.storage_path(row["storage_key"])
    if not path.exists():
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文件不存在")
    return path, row["filename"], row["mime_type"]
