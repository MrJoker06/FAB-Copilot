from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fab_core import DomainError


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise DomainError(
                "APP_DATABASE_UNAVAILABLE",
                f"Application database is unavailable: {self.path.name}",
                status_code=503,
                retryable=True,
            )
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()


class KnowledgeRepository(SQLiteRepository):
    _DOMAIN_TERMS = (
        "CVD",
        "ETCH",
        "LITHO",
        "CMP",
        "PVD",
        "IMPLANT",
        "DIFFUSION",
        "CLEAN",
        "METROLOGY",
        "膜厚",
        "漂移",
        "颗粒",
        "缺陷",
        "异常",
        "良率",
        "根因",
        "处置",
        "设备",
        "传感器",
        "清洗",
        "刻蚀",
        "光刻",
        "沉积",
        "污染",
        "划伤",
        "残留",
    )

    def list_documents(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT d.title, d.source, d.doc_type, d.version, d.status,
                          d.effective_date, d.owner, d.authority, d.process_steps, d.tags,
                          COUNT(k.chunk_id) AS section_count,
                          GROUP_CONCAT(k.section, ' · ') AS sections,
                          MIN(k.chunk_id) AS first_chunk_id
                   FROM knowledge_documents d
                   JOIN knowledge_chunks k ON k.source = d.source
                   WHERE d.status = 'Active'
                   GROUP BY d.source
                   ORDER BY d.source"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document(self, chunk_id: int) -> dict[str, Any]:
        with self.connection() as connection:
            selected = connection.execute(
                """SELECT k.chunk_id, k.title, k.source, k.section, d.doc_type, d.version,
                          d.status, d.effective_date, d.owner, d.authority, d.process_steps, d.tags
                   FROM knowledge_chunks k JOIN knowledge_documents d ON d.source = k.source
                   WHERE k.chunk_id = ?""",
                (chunk_id,),
            ).fetchone()
            if selected is None:
                raise DomainError("KNOWLEDGE_NOT_FOUND", "知识章节不存在", status_code=404)
            rows = connection.execute(
                """SELECT chunk_id, title, source, section, content
                   FROM knowledge_chunks WHERE source = ? ORDER BY chunk_id""",
                (selected["source"],),
            ).fetchall()
        return {
            "selected_chunk_id": chunk_id,
            "document": dict(selected),
            "chunks": [dict(row) for row in rows],
        }

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Search governed documents and validated cases without querying manufacturing data."""
        cleaned = " ".join(query.strip().split())
        requested_limit = max(1, min(int(limit), 10))
        latin_terms = re.findall(r"[A-Za-z0-9_-]{2,}", cleaned)
        domain_terms = [term for term in self._DOMAIN_TERMS if term.lower() in cleaned.lower()]
        terms = list(dict.fromkeys([*latin_terms, *domain_terms, cleaned]))[:8]
        patterns = [f"%{term}%" for term in terms if term]
        if not patterns:
            return []
        document_where = " OR ".join(
            ["(k.title LIKE ? OR k.section LIKE ? OR k.content LIKE ?)"] * len(patterns)
        )
        document_params = [value for pattern in patterns for value in (pattern, pattern, pattern)]
        case_where = " OR ".join(
            ["(c.title LIKE ? OR c.problem LIKE ? OR c.summary LIKE ? OR c.root_cause LIKE ?)"]
            * len(patterns)
        )
        case_params = [value for pattern in patterns for value in (pattern, pattern, pattern, pattern)]
        with self.connection() as connection:
            documents = connection.execute(
                f"""SELECT k.chunk_id, k.title, k.source, k.section, k.content
                    FROM knowledge_chunks k
                    JOIN knowledge_documents d ON d.source = k.source
                    WHERE d.status = 'Active' AND ({document_where})
                    ORDER BY k.chunk_id LIMIT ?""",
                [*document_params, requested_limit],
            ).fetchall()
            remaining = max(0, requested_limit - len(documents))
            cases = []
            if remaining:
                cases = connection.execute(
                    f"""SELECT c.case_id, c.title, c.process_step, c.equipment_id,
                               c.summary, c.root_cause
                        FROM historical_cases c
                        WHERE c.case_status = 'Validated' AND ({case_where})
                        ORDER BY c.occurred_date DESC LIMIT ?""",
                    [*case_params, remaining],
                ).fetchall()
        results = [
            {
                "source_type": "knowledge",
                "reference_id": f"KB-{row['chunk_id']}",
                "chunk_id": row["chunk_id"],
                "title": row["title"],
                "source": row["source"],
                "section": row["section"],
                "excerpt": str(row["content"])[:800],
            }
            for row in documents
        ]
        results.extend(
            {
                "source_type": "case",
                "reference_id": row["case_id"],
                "case_id": row["case_id"],
                "title": row["title"],
                "source": row["title"],
                "section": "已验证历史案例",
                "excerpt": "；".join(value for value in (row["summary"], row["root_cause"]) if value)[:800],
                "process_step": row["process_step"],
                "equipment_id": row["equipment_id"],
            }
            for row in cases
        )
        return results

    def list_cases(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT case_id, title, process_step, equipment_id, occurred_date,
                          severity, problem, summary, tags, equipment_family, defect_type,
                          root_cause_confidence, recurrence_status, case_status
                   FROM historical_cases
                   WHERE case_status = 'Validated'
                   ORDER BY occurred_date DESC, case_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT case_id, title, process_step, equipment_id, occurred_date,
                          severity, problem, solution, result, summary, tags,
                          equipment_family, defect_type, symptoms, root_cause,
                          root_cause_confidence, validation_method, recurrence_status,
                          approved_by, case_status
                   FROM historical_cases WHERE case_id = ? AND case_status = 'Validated'""",
                (case_id,),
            ).fetchone()
        if row is None:
            raise DomainError("CASE_NOT_FOUND", "历史案例不存在", status_code=404)
        return dict(row)


class SessionRepository(SQLiteRepository):
    def create(self, title: str = "新会话") -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        timestamp = _now()
        cleaned = " ".join(title.strip().split())[:80] or "新会话"
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO chat_sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, cleaned, timestamp, timestamp),
            )
            connection.commit()
        return {"session_id": session_id, "title": cleaned, "created_at": timestamp, "updated_at": timestamp}

    def list(self, query: str = "", limit: int = 100, include_archived: bool = False) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if not include_archived:
            clauses.append("s.archived_at IS NULL")
        if query.strip():
            clauses.append("(s.title LIKE ? OR s.last_message_preview LIKE ?)")
            value = f"%{query.strip()}%"
            params.extend([value, value])
        params.append(max(1, min(limit, 200)))
        with self.connection() as connection:
            rows = connection.execute(
                f"""SELECT s.session_id, s.title, s.created_at, s.updated_at, s.model,
                           s.archived_at, s.last_message_preview,
                           COUNT(m.message_id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.session_id
                    WHERE {" AND ".join(clauses)}
                    GROUP BY s.session_id
                    ORDER BY s.updated_at DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            session = connection.execute(
                """SELECT session_id, title, created_at, updated_at, model, archived_at
                   FROM chat_sessions WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            if session is None:
                raise DomainError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
            rows = connection.execute(
                """SELECT message_id, role, content, metadata_json, created_at
                   FROM chat_messages WHERE session_id = ? ORDER BY message_id""",
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
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

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        cleaned = " ".join(title.strip().split())[:80]
        if not cleaned:
            raise DomainError("INVALID_TITLE", "会话标题不能为空", status_code=422)
        timestamp = _now()
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (cleaned, timestamp, session_id),
            )
            if cursor.rowcount == 0:
                raise DomainError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
            connection.commit()
        return {"session_id": session_id, "title": cleaned, "updated_at": timestamp}

    def set_archived(self, session_id: str, archived: bool) -> dict[str, Any]:
        timestamp = _now()
        archived_at = timestamp if archived else None
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE chat_sessions SET archived_at = ?, updated_at = ? WHERE session_id = ?",
                (archived_at, timestamp, session_id),
            )
            if cursor.rowcount == 0:
                raise DomainError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
            connection.commit()
        return {"session_id": session_id, "archived_at": archived_at, "updated_at": timestamp}

    def delete(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            if cursor.rowcount == 0:
                raise DomainError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
            connection.commit()
        return {"session_id": session_id, "deleted": True}

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise DomainError("INVALID_ROLE", "不支持的消息角色", status_code=422)
        timestamp = _now()
        with self.connection() as connection:
            session = connection.execute(
                "SELECT title FROM chat_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise DomainError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
            cursor = connection.execute(
                """INSERT INTO chat_messages(session_id, role, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), timestamp),
            )
            title = session["title"]
            if role == "user" and title == "新会话":
                title = " ".join(content.strip().split())[:50] or title
            preview = " ".join(content.strip().split())[:140]
            connection.execute(
                """UPDATE chat_sessions SET title = ?, updated_at = ?, last_message_preview = ?,
                          archived_at = NULL, model = COALESCE(?, model)
                   WHERE session_id = ?""",
                (title, timestamp, preview, model, session_id),
            )
            connection.commit()
        return {
            "message_id": cursor.lastrowid,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": timestamp,
        }
