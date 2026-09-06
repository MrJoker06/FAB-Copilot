"""Persistent job state transitions for personal knowledge documents."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable

from .contracts import PersonalKnowledgeError


def latest_job(connection, document_id: str, owner_user_id: str):
    return connection.execute(
        """SELECT job_id, document_id, status, stage, progress, attempt,
                  error_code, error_message, retryable, created_at, updated_at
           FROM personal_knowledge_jobs
           WHERE document_id = ? AND owner_user_id = ?
           ORDER BY attempt DESC, created_at DESC, job_id DESC LIMIT 1""",
        (document_id, owner_user_id),
    ).fetchone()


def initial_upload_job(connection, document_id: str, owner_user_id: str):
    return connection.execute(
        """SELECT job_id, document_id, status, stage, progress, attempt,
                  error_code, error_message, retryable, created_at, updated_at
           FROM personal_knowledge_jobs
           WHERE document_id = ? AND owner_user_id = ?
           ORDER BY attempt ASC, created_at ASC, job_id ASC LIMIT 1""",
        (document_id, owner_user_id),
    ).fetchone()


def job_dict(row) -> dict:
    item = dict(row)
    error_code = item.pop("error_code", None)
    error_message = item.pop("error_message", None)
    retryable = bool(item.pop("retryable", 0))
    item["error"] = (
        {"error_code": error_code, "detail": error_message, "retryable": retryable}
        if error_code
        else None
    )
    return item


def update_progress(
    db_session: Callable,
    document_id: str,
    owner_user_id: str,
    job_id: str,
    status: str,
    stage: str,
    progress: int,
    *,
    now: Callable[[], str],
) -> None:
    timestamp = now()
    with db_session() as connection:
        connection.execute(
            """UPDATE knowledge.personal_knowledge_documents
               SET status = ?, error_code = NULL, error_message = NULL, updated_at = ?
               WHERE document_id = ? AND owner_user_id = ?""",
            (status, timestamp, document_id, owner_user_id),
        )
        connection.execute(
            """UPDATE knowledge.personal_knowledge_jobs
               SET status = ?, stage = ?, progress = ?, error_code = NULL,
                   error_message = NULL, retryable = 0, updated_at = ?
               WHERE job_id = ? AND owner_user_id = ?""",
            (status, stage, progress, timestamp, job_id, owner_user_id),
        )
        connection.commit()


def mark_failed(
    db_session: Callable,
    document_id: str,
    owner_user_id: str,
    job_id: str,
    error_code: str,
    detail: str,
    retryable: bool,
    *,
    now: Callable[[], str],
) -> None:
    timestamp = now()
    with db_session() as connection:
        connection.execute(
            """UPDATE knowledge.personal_knowledge_documents
               SET status = 'failed', error_code = ?, error_message = ?, updated_at = ?
               WHERE document_id = ? AND owner_user_id = ?""",
            (error_code, detail, timestamp, document_id, owner_user_id),
        )
        connection.execute(
            """UPDATE knowledge.personal_knowledge_jobs
               SET status = 'failed', stage = 'failed', error_code = ?, error_message = ?,
                   retryable = ?, updated_at = ?
               WHERE job_id = ? AND owner_user_id = ?""",
            (error_code, detail, int(retryable), timestamp, job_id, owner_user_id),
        )
        connection.commit()


def get_job(db_session: Callable, job_id: str, owner_user_id: str) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT job_id, document_id, status, stage, progress, attempt,
                      error_code, error_message, retryable, created_at, updated_at
               FROM personal_knowledge_jobs WHERE job_id = ? AND owner_user_id = ?""",
            (job_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "任务不存在")
    return job_dict(row)


def list_job_snapshots(db_session: Callable, owner_user_id: str, limit: int = 100) -> list[dict]:
    with db_session() as connection:
        rows = connection.execute(
            """SELECT job_id, document_id, status, stage, progress, attempt,
                      error_code, error_message, retryable, created_at, updated_at
               FROM (
                 SELECT j.*, ROW_NUMBER() OVER (
                   PARTITION BY document_id ORDER BY attempt DESC, created_at DESC, job_id DESC
                 ) AS row_number
                 FROM personal_knowledge_jobs j WHERE owner_user_id = ?
               ) WHERE row_number = 1
               ORDER BY CASE WHEN status IN ('uploaded', 'parsing', 'chunking', 'indexing', 'deleting')
                             THEN 0 ELSE 1 END, updated_at DESC, job_id DESC LIMIT ?""",
            (owner_user_id, limit),
        ).fetchall()
    return [job_dict(row) for row in rows]


def retry_document(
    db_session: Callable,
    document_id: str,
    owner_user_id: str,
    *,
    now: Callable[[], str],
) -> dict:
    timestamp = now()
    with db_session() as connection:
        document = connection.execute(
            """SELECT * FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if document is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        if document["status"] != "failed":
            raise PersonalKnowledgeError(409, "INVALID_DOCUMENT_STATE", "只有失败的文档可以重试")
        if document["error_code"] == "DELETE_FAILED":
            raise PersonalKnowledgeError(409, "INVALID_DOCUMENT_STATE", "删除失败的文档应重新执行删除")
        attempt = connection.execute(
            "SELECT COALESCE(MAX(attempt), 0) + 1 FROM personal_knowledge_jobs WHERE document_id = ?",
            (document_id,),
        ).fetchone()[0]
        job_id = str(uuid.uuid4())
        connection.execute(
            """UPDATE knowledge.personal_knowledge_documents
               SET status = 'uploaded', error_code = NULL, error_message = NULL, updated_at = ?
               WHERE document_id = ? AND owner_user_id = ?""",
            (timestamp, document_id, owner_user_id),
        )
        connection.execute(
            """INSERT INTO knowledge.personal_knowledge_jobs(
                   job_id, document_id, owner_user_id, status, stage, progress, attempt,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'uploaded', 'queued', 0, ?, ?, ?)""",
            (job_id, document_id, owner_user_id, attempt, timestamp, timestamp),
        )
        connection.commit()
    return {"document_id": document_id, "job_id": job_id, "status": "uploaded", "status_url": f"/api/knowledge/jobs/{job_id}"}


def begin_delete(db_session: Callable, document_id: str, owner_user_id: str, *, now: Callable[[], str]) -> dict:
    timestamp = now()
    job_id = str(uuid.uuid4())
    with db_session() as connection:
        document = connection.execute(
            """SELECT status FROM personal_knowledge_documents
               WHERE document_id = ? AND owner_user_id = ?""",
            (document_id, owner_user_id),
        ).fetchone()
        if document is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        if document["status"] == "deleting":
            raise PersonalKnowledgeError(409, "INVALID_DOCUMENT_STATE", "文档已经在删除中")
        connection.execute(
            """UPDATE knowledge.personal_knowledge_documents SET status = 'deleting', updated_at = ?
               WHERE document_id = ? AND owner_user_id = ?""",
            (timestamp, document_id, owner_user_id),
        )
        connection.execute(
            """INSERT INTO knowledge.personal_knowledge_jobs(
                   job_id, document_id, owner_user_id, status, stage, progress, attempt,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'deleting', 'deleting', 0, 1, ?, ?)""",
            (job_id, document_id, owner_user_id, timestamp, timestamp),
        )
        connection.commit()
    return {"document_id": document_id, "job_id": job_id, "status": "deleting"}


def process_deletion(
    db_session: Callable,
    storage_path: Callable,
    emit: Callable,
    document_id: str,
    owner_user_id: str,
    job_id: str,
    *,
    now: Callable[[], str],
) -> None:
    try:
        with db_session() as connection:
            document = connection.execute(
                """SELECT storage_key FROM personal_knowledge_documents
                   WHERE document_id = ? AND owner_user_id = ?""",
                (document_id, owner_user_id),
            ).fetchone()
        if document is None:
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识文档不存在")
        path: Path = storage_path(document["storage_key"])
        path.unlink(missing_ok=True)
        for directory in (path.parent, path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass
        timestamp = now()
        with db_session() as connection:
            connection.execute(
                """DELETE FROM knowledge.personal_knowledge_fts
                   WHERE document_id = ? AND owner_user_id = ?""",
                (document_id, owner_user_id),
            )
            connection.execute(
                """DELETE FROM knowledge.personal_knowledge_documents
                   WHERE document_id = ? AND owner_user_id = ?""",
                (document_id, owner_user_id),
            )
            connection.execute(
                """UPDATE knowledge.personal_knowledge_jobs
                   SET status = 'deleted', stage = 'deleted', progress = 100, updated_at = ?
                   WHERE job_id = ? AND owner_user_id = ?""",
                (timestamp, job_id, owner_user_id),
            )
            connection.commit()
        emit("personal_knowledge_deleted", job_id, status="success", document_id=document_id)
    except Exception as exc:
        timestamp = now()
        with db_session() as connection:
            connection.execute(
                """UPDATE knowledge.personal_knowledge_documents
                   SET status = 'failed', error_code = 'DELETE_FAILED',
                       error_message = '个人知识文档删除失败', updated_at = ?
                   WHERE document_id = ? AND owner_user_id = ?""",
                (timestamp, document_id, owner_user_id),
            )
            connection.execute(
                """UPDATE knowledge.personal_knowledge_jobs
                   SET status = 'failed', stage = 'failed', error_code = 'DELETE_FAILED',
                       error_message = '个人知识文档删除失败', retryable = 1, updated_at = ?
                   WHERE job_id = ? AND owner_user_id = ?""",
                (timestamp, job_id, owner_user_id),
            )
            connection.commit()
        emit("personal_knowledge_deleted", job_id, status="error", document_id=document_id, error_type=type(exc).__name__)


def pending_jobs(db_session: Callable) -> list[tuple[str, str, str, str]]:
    with db_session() as connection:
        rows = connection.execute(
            """SELECT j.document_id, j.owner_user_id, j.job_id, d.status
               FROM personal_knowledge_jobs j
               JOIN personal_knowledge_documents d ON d.document_id = j.document_id
               WHERE j.status IN ('uploaded', 'parsing', 'chunking', 'indexing', 'deleting')
                 AND j.created_at = (SELECT MAX(j2.created_at) FROM personal_knowledge_jobs j2
                                      WHERE j2.document_id = j.document_id)"""
        ).fetchall()
    return [(row["document_id"], row["owner_user_id"], row["job_id"], row["status"]) for row in rows]
