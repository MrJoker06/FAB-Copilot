"""Passive, database-backed circuit breaker for governed model calls.

This module never probes providers.  It records only a small failure category,
so operational diagnostics cannot accidentally retain request/response content.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .persistence.database import db_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="milliseconds")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _public(row) -> dict:
    item = dict(row)
    return {
        "status": item.get("status", "unknown"),
        "consecutive_failures": int(item.get("consecutive_failures") or 0),
        "opened_at": item.get("opened_at"),
        "open_until": item.get("open_until"),
        "last_success_at": item.get("last_success_at"),
        "last_failure_at": item.get("last_failure_at"),
        "last_error_category": item.get("last_error_category"),
    }


def ensure_model_health(model_id: str, connection=None) -> None:
    own = connection is None
    if own:
        context = db_session()
        connection = context.__enter__()
    try:
        connection.execute(
            "INSERT OR IGNORE INTO agent.model_health(model_id, updated_at) VALUES (?, ?)",
            (model_id, _stamp()),
        )
        if own:
            connection.commit()
    finally:
        if own:
            context.__exit__(None, None, None)


def get_model_health(model_id: str) -> dict:
    with db_session() as connection:
        ensure_model_health(model_id, connection)
        row = connection.execute("SELECT * FROM agent.model_health WHERE model_id = ?", (model_id,)).fetchone()
        connection.commit()
    return _public(row)


def claim_model_call(model_id: str, *, cooldown_seconds: int, lease_seconds: int) -> tuple[bool, dict, str | None]:
    """Atomically reserve a model call; returns (allowed, health, transition)."""
    now = _now()
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_model_health(model_id, connection)
        row = connection.execute("SELECT * FROM agent.model_health WHERE model_id = ?", (model_id,)).fetchone()
        status = row["status"]
        until = _parse(row["open_until"])
        claimed = _parse(row["recovery_claimed_at"])
        transition = None
        allowed = True
        if status == "open":
            if until is not None and until > now:
                allowed = False
            else:
                status, transition = "half_open", "recovery_started"
                connection.execute("UPDATE agent.model_health SET status=?, recovery_claimed_at=?, updated_at=? WHERE model_id=?", (status, _stamp(now), _stamp(now), model_id))
        elif status == "half_open":
            if claimed is not None and claimed + timedelta(seconds=lease_seconds) > now:
                allowed = False
            else:
                transition = "recovery_reclaimed"
                connection.execute("UPDATE agent.model_health SET recovery_claimed_at=?, updated_at=? WHERE model_id=?", (_stamp(now), _stamp(now), model_id))
        row = connection.execute("SELECT * FROM agent.model_health WHERE model_id = ?", (model_id,)).fetchone()
        connection.commit()
    return allowed, _public(row), transition


def record_model_success(model_id: str) -> tuple[dict, str | None]:
    now = _stamp()
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_model_health(model_id, connection)
        row = connection.execute("SELECT status FROM agent.model_health WHERE model_id=?", (model_id,)).fetchone()
        transition = "recovered" if row["status"] in {"open", "half_open"} else None
        connection.execute("""UPDATE agent.model_health SET status='healthy', consecutive_failures=0,
            opened_at=NULL, open_until=NULL, recovery_claimed_at=NULL, last_success_at=?,
            last_error_category=NULL, updated_at=? WHERE model_id=?""", (now, now, model_id))
        result = connection.execute("SELECT * FROM agent.model_health WHERE model_id=?", (model_id,)).fetchone()
        connection.commit()
    return _public(result), transition


def record_model_failure(model_id: str, category: str, *, threshold: int, cooldown_seconds: int) -> tuple[dict, str | None]:
    """Record one final availability failure, never an exception body."""
    now_dt, now = _now(), _stamp()
    category = category if category in {"network", "timeout", "rate_limit", "upstream_5xx"} else "network"
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ensure_model_health(model_id, connection)
        row = connection.execute("SELECT * FROM agent.model_health WHERE model_id=?", (model_id,)).fetchone()
        failures = int(row["consecutive_failures"] or 0) + 1
        should_open = row["status"] == "half_open" or failures >= threshold
        if should_open:
            status, transition = "open", "opened"
            opened_at, open_until = now, _stamp(now_dt + timedelta(seconds=cooldown_seconds))
        else:
            status, transition, opened_at, open_until = "degraded", None, None, None
        connection.execute("""UPDATE agent.model_health SET status=?, consecutive_failures=?, opened_at=?,
            open_until=?, recovery_claimed_at=NULL, last_failure_at=?, last_error_category=?, updated_at=?
            WHERE model_id=?""", (status, failures, opened_at, open_until, now, category, now, model_id))
        result = connection.execute("SELECT * FROM agent.model_health WHERE model_id=?", (model_id,)).fetchone()
        connection.commit()
    return _public(result), transition
