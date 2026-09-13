from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..persistence.database import db_session
from ..persistence.execution_store import executions_for_session
from ..core.identity import current_principal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _scope() -> tuple[str, str]:
    principal = current_principal()
    return principal.tenant_id, principal.user_id


def create_session(title: str = "新会话") -> dict:
    session_id = str(uuid.uuid4())
    timestamp = _now()
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        connection.execute(
            """INSERT INTO agent.chat_sessions(
                   session_id, tenant_id, owner_user_id, title, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, tenant_id, owner_user_id, title[:80] or "新会话", timestamp, timestamp),
        )
        connection.commit()
    return {"session_id": session_id, "title": title[:80] or "新会话", "created_at": timestamp, "updated_at": timestamp}


def get_session(session_id: str) -> dict:
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        session = connection.execute(
            """SELECT session_id, title, created_at, updated_at, model, archived_at
               FROM chat_sessions
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (session_id, tenant_id, owner_user_id),
        ).fetchone()
        if session is None:
            raise ValueError("会话不存在")
        rows = connection.execute(
            """SELECT message_id, role, content, metadata_json, created_at
               FROM chat_messages WHERE session_id = ? ORDER BY message_id""",
            (session_id,),
        ).fetchall()
        executions = executions_for_session(connection, session_id)
    messages = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        if item["role"] == "assistant" and item["message_id"] in executions:
            item["metadata"]["execution"] = executions[item["message_id"]]
        messages.append(item)
    result = dict(session)
    result["messages"] = messages
    return result


def list_sessions(query: str = "", limit: int = 100, include_archived: bool = False) -> list[dict]:
    tenant_id, owner_user_id = _scope()
    clauses = ["s.tenant_id = ?", "s.owner_user_id = ?"]
    params: list[object] = [tenant_id, owner_user_id]
    if not include_archived:
        clauses.append("s.archived_at IS NULL")
    if query.strip():
        clauses.append("(s.title LIKE ? OR s.last_message_preview LIKE ?)")
        value = f"%{query.strip()}%"
        params.extend([value, value])
    params.append(max(1, min(limit, 200)))
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT s.session_id, s.title, s.created_at, s.updated_at, s.model,
                       s.archived_at, s.last_message_preview,
                       COUNT(m.message_id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                WHERE {' AND '.join(clauses)}
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def rename_session(session_id: str, title: str) -> dict:
    cleaned = " ".join(title.strip().split())[:80]
    if not cleaned:
        raise ValueError("会话标题不能为空")
    timestamp = _now()
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        cursor = connection.execute(
            """UPDATE agent.chat_sessions SET title = ?, updated_at = ?
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (cleaned, timestamp, session_id, tenant_id, owner_user_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "title": cleaned, "updated_at": timestamp}


def archive_session(session_id: str) -> dict:
    timestamp = _now()
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        cursor = connection.execute(
            """UPDATE agent.chat_sessions SET archived_at = ?, updated_at = ?
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (timestamp, timestamp, session_id, tenant_id, owner_user_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "archived_at": timestamp}


def restore_session(session_id: str) -> dict:
    timestamp = _now()
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        cursor = connection.execute(
            """UPDATE agent.chat_sessions SET archived_at = NULL, updated_at = ?
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (timestamp, session_id, tenant_id, owner_user_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "archived_at": None, "updated_at": timestamp}


def delete_session_permanently(session_id: str) -> dict:
    result = delete_sessions_permanently([session_id])
    if not result["deleted_session_ids"]:
        raise ValueError("会话不存在")
    return {"session_id": session_id, "deleted": True}


def delete_sessions_permanently(session_ids: list[str]) -> dict:
    unique_ids = list(dict.fromkeys(session_ids))
    if not unique_ids:
        return {"deleted_session_ids": [], "deleted_count": 0, "missing_session_ids": []}
    placeholders = ", ".join("?" for _ in unique_ids)
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        existing_ids = {
            row[0]
            for row in connection.execute(
                f"""SELECT session_id FROM chat_sessions
                    WHERE tenant_id = ? AND owner_user_id = ?
                      AND session_id IN ({placeholders})""",
                [tenant_id, owner_user_id, *unique_ids],
            ).fetchall()
        }
        deleted_ids = [session_id for session_id in unique_ids if session_id in existing_ids]
        missing_ids = [session_id for session_id in unique_ids if session_id not in existing_ids]
        if not deleted_ids:
            return {
                "deleted_session_ids": [],
                "deleted_count": 0,
                "missing_session_ids": missing_ids,
            }
        delete_placeholders = ", ".join("?" for _ in deleted_ids)
        connection.execute(
            f"""DELETE FROM agent.chat_sessions
                WHERE tenant_id = ? AND owner_user_id = ?
                  AND session_id IN ({delete_placeholders})""",
            [tenant_id, owner_user_id, *deleted_ids],
        )
        connection.commit()
    return {
        "deleted_session_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
        "missing_session_ids": missing_ids,
    }


def session_history(session_id: str, limit: int = 20) -> list[dict]:
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        exists = connection.execute(
            """SELECT 1 FROM chat_sessions
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (session_id, tenant_id, owner_user_id),
        ).fetchone()
        if exists is None:
            raise ValueError("会话不存在")
        rows = connection.execute(
            """SELECT message_id, role, content, metadata_json FROM (
                   SELECT message_id, role, content, metadata_json FROM chat_messages
                   WHERE session_id = ? ORDER BY message_id DESC LIMIT ?
               ) ORDER BY message_id""",
            (session_id, max(1, min(limit, 20))),
        ).fetchall()
    history: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        history.append(item)
    return history


def cached_agent_result(session_id: str, client_message_id: str | None) -> dict | None:
    if not client_message_id:
        return None
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        row = connection.execute(
            """SELECT m.content, m.metadata_json FROM chat_messages m
               JOIN chat_sessions s ON s.session_id = m.session_id
               WHERE m.session_id = ? AND m.role = 'assistant'
                 AND s.tenant_id = ? AND s.owner_user_id = ?
                 AND json_extract(metadata_json, '$.client_message_id') = ?
               ORDER BY m.message_id DESC LIMIT 1""",
            (session_id, tenant_id, owner_user_id, client_message_id),
        ).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        result = {}
    result["answer"] = row["content"]
    result["client_message_id"] = client_message_id
    result["cached"] = True
    return result


def client_message_content(session_id: str, client_message_id: str | None) -> str | None:
    if not client_message_id:
        return None
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        row = connection.execute(
            """SELECT m.content FROM chat_messages m
               JOIN chat_sessions s ON s.session_id = m.session_id
               WHERE m.session_id = ? AND m.role = 'user' AND m.client_message_id = ?
                 AND s.tenant_id = ? AND s.owner_user_id = ?""",
            (session_id, client_message_id, tenant_id, owner_user_id),
        ).fetchone()
    return None if row is None else str(row["content"])


def append_message(
    session_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
    client_message_id: str | None = None,
) -> dict:
    if role not in {"user", "assistant"}:
        raise ValueError("不支持的消息角色")
    timestamp = _now()
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        session = connection.execute(
            """SELECT title FROM chat_sessions
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (session_id, tenant_id, owner_user_id),
        ).fetchone()
        if session is None:
            raise ValueError("会话不存在")
        if role == "user" and client_message_id:
            existing = connection.execute(
                """SELECT message_id, role, content, metadata_json, created_at
                   FROM chat_messages WHERE session_id = ? AND role = 'user' AND client_message_id = ?""",
                (session_id, client_message_id),
            ).fetchone()
            if existing is not None:
                try:
                    existing_metadata = json.loads(existing["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    existing_metadata = {}
                return {
                    "message_id": existing["message_id"],
                    "role": existing["role"],
                    "content": existing["content"],
                    "metadata": existing_metadata,
                    "created_at": existing["created_at"],
                    "client_message_id": client_message_id,
                    "duplicate": True,
                }
        cursor = connection.execute(
            """INSERT INTO agent.chat_messages(session_id, role, content, metadata_json, client_message_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
                client_message_id if role == "user" else None,
                timestamp,
            ),
        )
        title = session["title"]
        if role == "user" and title == "新会话":
            title = content.strip().replace("\n", " ")[:50] or title
        model = str((metadata or {}).get("model") or "") if role == "assistant" else ""
        preview = " ".join(content.strip().split())[:140]
        connection.execute(
            """UPDATE agent.chat_sessions
               SET title = ?, updated_at = ?, last_message_preview = ?,
                   model = CASE WHEN ? = '' THEN model ELSE ? END,
                   archived_at = NULL
               WHERE session_id = ?""",
            (title, timestamp, preview, model, model, session_id),
        )
        connection.commit()
    return {
        "message_id": cursor.lastrowid,
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "created_at": timestamp,
        "client_message_id": client_message_id if role == "user" else None,
        "duplicate": False,
    }


def record_agent_result(
    session_id: str,
    assistant_message_id: int,
    result: dict,
    *,
    user_message_id: int | None = None,
    question: str = "",
) -> None:
    run_id = str(result.get("run_id") or "")
    if not run_id:
        return
    completed_at = str(result.get("completed_at") or _now())
    result_started_at = result.get("started_at")
    usage = result.get("usage") or {}
    tenant_id, owner_user_id = _scope()
    with db_session() as connection:
        owned = connection.execute(
            """SELECT 1 FROM chat_sessions
               WHERE session_id = ? AND tenant_id = ? AND owner_user_id = ?""",
            (session_id, tenant_id, owner_user_id),
        ).fetchone()
        if owned is None:
            raise ValueError("会话不存在")
        existing_run = connection.execute(
            "SELECT started_at FROM agent_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        started_at = str(
            result_started_at
            or (existing_run["started_at"] if existing_run is not None else "")
            or completed_at
        )
        if user_message_id is None:
            user_message = connection.execute(
                """SELECT message_id, content FROM chat_messages
                   WHERE session_id = ? AND role = 'user' AND message_id < ?
                   ORDER BY message_id DESC LIMIT 1""",
                (session_id, assistant_message_id),
            ).fetchone()
        else:
            user_message = connection.execute(
                """SELECT message_id, content FROM chat_messages
                   WHERE message_id = ? AND session_id = ? AND role = 'user'""",
                (user_message_id, session_id),
            ).fetchone()
            if user_message is None:
                raise ValueError("Agent Run 对应的用户消息不存在")
        resolved_user_message_id = user_message["message_id"] if user_message is not None else None
        question_preview = " ".join((question or (user_message["content"] if user_message else "")).strip().split())[:240]
        connection.execute(
            """INSERT INTO agent.agent_runs(
                   run_id, session_id, user_message_id, assistant_message_id, question_preview,
                   model, mode, status,
                   started_at, completed_at, first_token_ms, duration_ms,
                   input_tokens, output_tokens, error_message
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                   session_id = excluded.session_id,
                   user_message_id = excluded.user_message_id,
                   assistant_message_id = excluded.assistant_message_id,
                   question_preview = excluded.question_preview,
                   model = CASE WHEN excluded.model = '' THEN agent_runs.model ELSE excluded.model END,
                   mode = excluded.mode,
                   status = excluded.status,
                   started_at = excluded.started_at,
                   completed_at = excluded.completed_at,
                   first_token_ms = excluded.first_token_ms,
                   duration_ms = excluded.duration_ms,
                   input_tokens = excluded.input_tokens,
                   output_tokens = excluded.output_tokens,
                   error_message = excluded.error_message""",
            (
                run_id, session_id, resolved_user_message_id, assistant_message_id, question_preview,
                str(result.get("model") or ""),
                str(result.get("mode") or "unknown"), str(result.get("status") or "success"),
                started_at, completed_at, result.get("first_token_ms"), result.get("duration_ms"),
                int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0),
                result.get("error_message"),
            ),
        )
        trace = result.get("tool_trace") or []
        for sequence_no, item in enumerate(trace, start=1):
            connection.execute(
                """INSERT INTO agent.agent_tool_events(
                       run_id, sequence_no, tool_name, arguments_json, status,
                       row_count, duration_ms, error_message, completed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, sequence_no) DO UPDATE SET
                       tool_name = excluded.tool_name,
                       arguments_json = excluded.arguments_json,
                       status = excluded.status,
                       row_count = excluded.row_count,
                       duration_ms = excluded.duration_ms,
                       error_message = excluded.error_message,
                       completed_at = COALESCE(agent_tool_events.completed_at, excluded.completed_at)""",
                (
                    run_id, sequence_no, str(item.get("tool") or "unknown"),
                    json.dumps(item.get("arguments") or {}, ensure_ascii=False, default=str),
                    str(item.get("status") or "unknown"), item.get("rows"),
                    item.get("duration_ms"), item.get("error"), completed_at,
                ),
            )
        connection.execute(
            "DELETE FROM agent.agent_tool_events WHERE run_id = ? AND sequence_no > ?",
            (run_id, len(trace)),
        )
        connection.execute("DELETE FROM agent.message_sources WHERE message_id = ?", (assistant_message_id,))
        for source in result.get("sources") or []:
            locator = str(source.get("case_id") or source.get("chunk_id") or source.get("source") or "")
            connection.execute(
                """INSERT INTO agent.message_sources(
                       message_id, reference_id, source_type, source_locator, title, section
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    assistant_message_id, str(source.get("reference_id") or ""),
                    str(source.get("source_type") or "knowledge"), locator,
                    str(source.get("title") or source.get("source") or ""),
                    str(source.get("section") or ""),
                ),
            )
        connection.commit()
