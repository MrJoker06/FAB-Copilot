from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .database import db_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def create_session(title: str = "新会话") -> dict:
    session_id = str(uuid.uuid4())
    timestamp = _now()
    with db_session() as connection:
        connection.execute(
            "INSERT INTO agent.chat_sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title[:80] or "新会话", timestamp, timestamp),
        )
        connection.commit()
    return {"session_id": session_id, "title": title[:80] or "新会话", "created_at": timestamp, "updated_at": timestamp}


def get_session(session_id: str) -> dict:
    with db_session() as connection:
        session = connection.execute(
            """SELECT session_id, title, created_at, updated_at, model, archived_at
               FROM chat_sessions WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError("会话不存在")
        rows = connection.execute(
            """SELECT message_id, role, content, metadata_json, created_at
               FROM chat_messages WHERE session_id = ? ORDER BY message_id""",
            (session_id,),
        ).fetchall()
    messages = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        messages.append(item)
    result = dict(session)
    result["messages"] = messages
    return result


def list_sessions(query: str = "", limit: int = 100, include_archived: bool = False) -> list[dict]:
    clauses = ["1 = 1"]
    params: list[object] = []
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
    with db_session() as connection:
        cursor = connection.execute(
            "UPDATE agent.chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (cleaned, timestamp, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "title": cleaned, "updated_at": timestamp}


def archive_session(session_id: str) -> dict:
    timestamp = _now()
    with db_session() as connection:
        cursor = connection.execute(
            "UPDATE agent.chat_sessions SET archived_at = ?, updated_at = ? WHERE session_id = ?",
            (timestamp, timestamp, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "archived_at": timestamp}


def restore_session(session_id: str) -> dict:
    timestamp = _now()
    with db_session() as connection:
        cursor = connection.execute(
            "UPDATE agent.chat_sessions SET archived_at = NULL, updated_at = ? WHERE session_id = ?",
            (timestamp, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("会话不存在")
        connection.commit()
    return {"session_id": session_id, "archived_at": None, "updated_at": timestamp}


def delete_session_permanently(session_id: str) -> dict:
    with db_session() as connection:
        session = connection.execute(
            "SELECT 1 FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError("会话不存在")
        connection.execute(
            "DELETE FROM agent.chat_sessions WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    return {"session_id": session_id, "deleted": True}


def session_history(session_id: str, limit: int = 8) -> list[dict]:
    with db_session() as connection:
        exists = connection.execute("SELECT 1 FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if exists is None:
            raise ValueError("会话不存在")
        rows = connection.execute(
            """SELECT role, content FROM (
                   SELECT message_id, role, content FROM chat_messages
                   WHERE session_id = ? ORDER BY message_id DESC LIMIT ?
               ) ORDER BY message_id""",
            (session_id, max(1, min(limit, 20))),
        ).fetchall()
    return [dict(row) for row in rows]


def append_message(session_id: str, role: str, content: str, metadata: dict | None = None) -> dict:
    if role not in {"user", "assistant"}:
        raise ValueError("不支持的消息角色")
    timestamp = _now()
    with db_session() as connection:
        session = connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError("会话不存在")
        cursor = connection.execute(
            """INSERT INTO agent.chat_messages(session_id, role, content, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False, default=str), timestamp),
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
    return {"message_id": cursor.lastrowid, "role": role, "content": content, "metadata": metadata or {}, "created_at": timestamp}


def record_agent_result(session_id: str, assistant_message_id: int, result: dict) -> None:
    run_id = str(result.get("run_id") or "")
    if not run_id:
        return
    completed_at = str(result.get("completed_at") or _now())
    started_at = str(result.get("started_at") or completed_at)
    usage = result.get("usage") or {}
    with db_session() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO agent.agent_runs(
                   run_id, session_id, assistant_message_id, model, mode, status,
                   started_at, completed_at, first_token_ms, duration_ms,
                   input_tokens, output_tokens, error_message
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, session_id, assistant_message_id, str(result.get("model") or ""),
                str(result.get("mode") or "unknown"), str(result.get("status") or "success"),
                started_at, completed_at, result.get("first_token_ms"), result.get("duration_ms"),
                int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0),
                result.get("error_message"),
            ),
        )
        connection.execute("DELETE FROM agent.agent_tool_events WHERE run_id = ?", (run_id,))
        for sequence_no, item in enumerate(result.get("tool_trace") or [], start=1):
            connection.execute(
                """INSERT INTO agent.agent_tool_events(
                       run_id, sequence_no, tool_name, arguments_json, status,
                       row_count, duration_ms, error_message
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, sequence_no, str(item.get("tool") or "unknown"),
                    json.dumps(item.get("arguments") or {}, ensure_ascii=False, default=str),
                    str(item.get("status") or "unknown"), item.get("rows"),
                    item.get("duration_ms"), item.get("error"),
                ),
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
