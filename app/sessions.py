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
            "INSERT INTO chat_sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title[:80] or "新会话", timestamp, timestamp),
        )
        connection.commit()
    return {"session_id": session_id, "title": title[:80] or "新会话", "created_at": timestamp, "updated_at": timestamp}


def get_session(session_id: str) -> dict:
    with db_session() as connection:
        session = connection.execute(
            "SELECT session_id, title, created_at, updated_at FROM chat_sessions WHERE session_id = ?",
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
            """INSERT INTO chat_messages(session_id, role, content, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False, default=str), timestamp),
        )
        title = session["title"]
        if role == "user" and title == "新会话":
            title = content.strip().replace("\n", " ")[:50] or title
        connection.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (title, timestamp, session_id),
        )
        connection.commit()
    return {"message_id": cursor.lastrowid, "role": role, "content": content, "metadata": metadata or {}, "created_at": timestamp}
