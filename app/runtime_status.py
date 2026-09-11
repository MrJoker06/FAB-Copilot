from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from .persistence.database import db_session
from .identity import Principal


_lock = threading.Lock()
_users: dict[tuple[str, str], dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="milliseconds")


def begin_agent_run(principal: Principal, session_id: str, question: str, model: str) -> None:
    key = (principal.tenant_id, principal.user_id)
    timestamp = _now()
    with _lock:
        current = _users.setdefault(key, {"active_runs": 0})
        current.update({
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "status": "running",
            "last_seen_at": _iso(timestamp),
            "last_started_at": _iso(timestamp),
            "session_id": session_id,
            "model": model,
            "question_preview": " ".join(question.strip().split())[:120],
            "last_error": "",
        })
        current["active_runs"] = int(current.get("active_runs", 0)) + 1


def finish_agent_run(
    principal: Principal,
    status: str,
    run_id: str = "",
    model: str = "",
    error: str = "",
) -> None:
    key = (principal.tenant_id, principal.user_id)
    timestamp = _now()
    with _lock:
        current = _users.setdefault(key, {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "active_runs": 0,
        })
        active_runs = max(0, int(current.get("active_runs", 0)) - 1)
        current.update({
            "active_runs": active_runs,
            "status": "running" if active_runs else ("error" if status == "error" else "idle"),
            "last_seen_at": _iso(timestamp),
            "last_completed_at": _iso(timestamp),
            "last_run_id": run_id,
            "last_error": " ".join(error.strip().split())[:240],
        })
        if model:
            current["model"] = model


def runtime_users() -> list[dict]:
    now = _now()
    with _lock:
        rows = [dict(item) for item in _users.values()]
    for item in rows:
        try:
            last_seen = datetime.fromisoformat(item.get("last_seen_at", ""))
        except ValueError:
            last_seen = now - timedelta(days=365)
        if not item.get("active_runs") and now - last_seen > timedelta(minutes=15):
            item["status"] = "offline"
    return rows


def admin_runtime_overview(hours: int = 24, recent_limit: int = 30) -> dict:
    hours = max(1, min(hours, 24 * 30))
    recent_limit = max(1, min(recent_limit, 100))
    cutoff = _iso(_now() - timedelta(hours=hours))
    with db_session() as connection:
        rows = connection.execute(
            """SELECT s.tenant_id, s.owner_user_id AS user_id,
                      COUNT(DISTINCT s.session_id) AS session_count,
                      MAX(s.updated_at) AS last_session_at,
                      COUNT(r.run_id) AS run_count,
                      SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END) AS success_runs,
                      SUM(CASE WHEN r.status IN ('error', 'interrupted') THEN 1 ELSE 0 END) AS failed_runs,
                      ROUND(AVG(r.duration_ms), 1) AS avg_duration_ms,
                      COALESCE(SUM(r.input_tokens), 0) AS input_tokens,
                      COALESCE(SUM(r.output_tokens), 0) AS output_tokens,
                      MAX(r.completed_at) AS last_run_at
               FROM chat_sessions s
               LEFT JOIN agent_runs r ON r.session_id = s.session_id AND r.completed_at >= ?
               WHERE s.updated_at >= ? OR r.run_id IS NOT NULL
               GROUP BY s.tenant_id, s.owner_user_id""",
            (cutoff, cutoff),
        ).fetchall()
        recent = connection.execute(
            """SELECT r.run_id, s.tenant_id, s.owner_user_id AS user_id,
                      s.session_id, s.title AS session_title, r.user_message_id,
                      COALESCE(NULLIF(r.question_preview, ''), substr(q.content, 1, 240), '') AS question_preview,
                      r.model, r.mode, r.status,
                      r.started_at, r.completed_at, r.duration_ms,
                      r.input_tokens, r.output_tokens, r.error_message
               FROM agent_runs r
               JOIN chat_sessions s ON s.session_id = r.session_id
               LEFT JOIN chat_messages q ON q.message_id = r.user_message_id
               WHERE r.completed_at >= ?
               ORDER BY r.completed_at DESC
               LIMIT ?""",
            (cutoff, recent_limit),
        ).fetchall()

    live = {(item["tenant_id"], item["user_id"]): item for item in runtime_users()}
    users = []
    persisted_keys = set()
    for row in rows:
        item = dict(row)
        key = (item["tenant_id"], item["user_id"])
        persisted_keys.add(key)
        runtime = live.get(key, {})
        item.update({
            "status": runtime.get("status", "offline"),
            "active_runs": runtime.get("active_runs", 0),
            "last_seen_at": runtime.get("last_seen_at") or item.get("last_run_at") or item.get("last_session_at"),
            "model": runtime.get("model", ""),
            "session_id": runtime.get("session_id", ""),
            "question_preview": runtime.get("question_preview", ""),
            "last_error": runtime.get("last_error", ""),
        })
        users.append(item)
    for key, runtime in live.items():
        if key in persisted_keys:
            continue
        users.append({
            **runtime,
            "session_count": 0,
            "run_count": 0,
            "success_runs": 0,
            "failed_runs": 0,
            "avg_duration_ms": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "last_session_at": None,
            "last_run_at": None,
        })
    status_order = {"running": 0, "error": 1, "idle": 2, "offline": 3}
    users.sort(key=lambda item: item.get("last_seen_at") or "", reverse=True)
    users.sort(key=lambda item: status_order.get(item.get("status"), 4))
    return {
        "window_hours": hours,
        "generated_at": _iso(),
        "summary": {
            "users": len(users),
            "online_users": sum(item.get("status") != "offline" for item in users),
            "running_users": sum(item.get("status") == "running" for item in users),
            "runs": sum(int(item.get("run_count", 0) or 0) for item in users),
            "failed_runs": sum(int(item.get("failed_runs", 0) or 0) for item in users),
            "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in users),
            "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in users),
        },
        "users": users,
        "recent_runs": [dict(row) for row in recent],
    }
