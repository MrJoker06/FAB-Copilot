from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import re
import subprocess
import threading
from collections import Counter
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .config import PROJECT_DIR


LOG_PATH = Path(os.getenv("AGENT_LOG_PATH", PROJECT_DIR / "logs" / "agent_events.jsonl"))
if not LOG_PATH.is_absolute():
    LOG_PATH = PROJECT_DIR / LOG_PATH
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
RUN_LOG_DIR = Path(os.getenv("AGENT_RUN_LOG_DIR", PROJECT_DIR / "logs" / "agent"))
if not RUN_LOG_DIR.is_absolute():
    RUN_LOG_DIR = PROJECT_DIR / RUN_LOG_DIR
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
SCHEMA_VERSION = "1.2"
_request_id: ContextVar[str | None] = ContextVar("fab_insight_request_id", default=None)


def _git_commit() -> str:
    configured = os.getenv("FAB_GIT_COMMIT", "").strip()
    if re.fullmatch(r"[0-9a-f]{7,40}|unversioned", configured, re.IGNORECASE):
        return configured
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_DIR), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() or "unversioned"
    except (OSError, subprocess.SubprocessError):
        return "unversioned"


GIT_COMMIT = _git_commit()
SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "password", "secret",
    "access_token", "refresh_token", "client_secret", "cookie", "set-cookie",
}
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
MAX_FULL_LOG_DURATION_HOURS = 24
LOG_POLICY_STARTED_AT = datetime.now(timezone.utc)


def _requested_content_mode() -> str:
    requested = os.getenv("AGENT_LOG_CONTENT", "metadata").strip().lower()
    return requested if requested in {"metadata", "redacted", "full"} else "metadata"


def log_content_policy(now: datetime | None = None, *, started_at: datetime | None = None) -> dict[str, Any]:
    """Return the current, safe-to-publish audit-content policy.

    This intentionally reads the environment on every call: expiry can take effect
    during a long request without a process reload.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    policy_started_at = started_at or LOG_POLICY_STARTED_AT
    if policy_started_at.tzinfo is None or policy_started_at.utcoffset() is None:
        policy_started_at = policy_started_at.replace(tzinfo=timezone.utc)
    policy_started_at = policy_started_at.astimezone(timezone.utc)
    requested_mode = _requested_content_mode()
    raw_expiry = os.getenv("AGENT_LOG_FULL_EXPIRES_AT", "").strip()
    full_test_mode = os.getenv("AGENT_LOG_FULL_TEST_MODE", "").strip().lower() in _TRUTHY_VALUES
    policy: dict[str, Any] = {
        "requested_mode": requested_mode,
        "effective_mode": requested_mode if requested_mode != "full" else "metadata",
        "status": "active" if requested_mode != "full" else "fallback",
        "reason": "requested_metadata" if requested_mode == "metadata" else "requested_redacted",
        "full_test_mode": full_test_mode,
        "expires_at": None,
        "remaining_seconds": None,
        "max_duration_hours": MAX_FULL_LOG_DURATION_HOURS,
    }
    if requested_mode != "full":
        return policy
    if not full_test_mode:
        policy["reason"] = "test_mode_disabled"
        return policy
    if not raw_expiry:
        policy["reason"] = "expiry_missing"
        return policy
    try:
        expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
    except ValueError:
        policy["reason"] = "expiry_invalid"
        return policy
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        policy["reason"] = "expiry_naive"
        return policy
    expires_at = expires_at.astimezone(timezone.utc)
    remaining_seconds = max(0, int((expires_at - current).total_seconds()))
    policy["expires_at"] = expires_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    policy["remaining_seconds"] = remaining_seconds
    if expires_at > policy_started_at + timedelta(hours=MAX_FULL_LOG_DURATION_HOURS):
        policy["reason"] = "expiry_exceeds_max_duration"
        return policy
    if expires_at <= current:
        policy["reason"] = "expiry_expired"
        return policy
    policy.update({"effective_mode": "full", "status": "active", "reason": "full_test_window_active"})
    return policy

_logger = logging.getLogger("fab_insight.agent_audit")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_lock = threading.Lock()

if not _logger.handlers:
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=int(os.getenv("AGENT_LOG_MAX_BYTES", str(5 * 1024 * 1024))),
        backupCount=int(os.getenv("AGENT_LOG_BACKUP_COUNT", "5")),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str) -> Token:
    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


def sanitize(value: Any) -> Any:
    """Remove credentials even when full-content test logging is enabled."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            is_sensitive = normalized in SENSITIVE_KEYS or normalized.endswith(("_api_key", "_password", "_secret", "_token"))
            sanitized[str(key)] = "<redacted>" if is_sensitive else sanitize(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def emit(event: str, run_id: str, *, full_content: Mapping[str, Any] | None = None, **fields: Any) -> None:
    policy = log_content_policy()
    request_id = current_request_id()
    record = sanitize({
        "timestamp": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "git_commit": GIT_COMMIT,
        "content_mode": policy["effective_mode"],
        "log_policy": policy,
        "event": event,
        "run_id": run_id,
        **({"request_id": request_id} if request_id else {}),
        **fields,
        **(dict(full_content) if policy["effective_mode"] == "full" and full_content else {}),
    })
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
    safe_run_id = "".join(character for character in run_id if character.isalnum() or character in {"-", "_"})[:120] or "unknown"
    day_directory = RUN_LOG_DIR / record["timestamp"][:10]
    with _lock:
        _logger.info(line)
        day_directory.mkdir(parents=True, exist_ok=True)
        with (day_directory / f"{safe_run_id}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _log_files() -> list[Path]:
    backups = sorted(LOG_PATH.parent.glob(f"{LOG_PATH.name}.*"), reverse=True)
    return backups + ([LOG_PATH] if LOG_PATH.exists() else [])


def read_events(limit: int = 5000) -> list[dict]:
    events: list[dict] = []
    for path in _log_files():
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    events.sort(key=lambda item: item.get("timestamp", ""))
    return events[-max(1, min(limit, 20000)):]


def monitoring_summary(hours: int = 24, recent_limit: int = 20) -> dict:
    hours = max(1, min(hours, 24 * 30))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = []
    for event in read_events():
        try:
            timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if timestamp >= cutoff:
            events.append(event)

    finished = [event for event in events if event.get("event") == "agent_run_finished"]
    model_calls = [event for event in events if event.get("event") == "model_call_finished"]
    tool_calls = [event for event in events if event.get("event") == "tool_call_finished"]
    success_count = sum(event.get("status") == "success" for event in finished)
    durations = sorted(float(event.get("duration_ms", 0)) for event in finished)
    p95_index = max(0, min(len(durations) - 1, round(len(durations) * 0.95) - 1)) if durations else 0
    tool_counter = Counter(event.get("tool", "unknown") for event in tool_calls)
    error_counter = Counter(event.get("error_type", "unknown") for event in events if event.get("status") == "error")

    recent_runs = sorted(finished, key=lambda item: item.get("timestamp", ""), reverse=True)[:max(1, min(recent_limit, 100))]
    return {
        "log_policy": log_content_policy(),
        "window_hours": hours,
        "log_path": str(LOG_PATH),
        "run_log_directory": str(RUN_LOG_DIR),
        "runs": len(finished),
        "success_runs": success_count,
        "failed_runs": len(finished) - success_count,
        "success_rate_pct": round(100 * success_count / len(finished), 2) if finished else None,
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "p95_duration_ms": round(durations[p95_index], 1) if durations else None,
        "model_calls": len(model_calls),
        "tool_calls": len(tool_calls),
        "input_tokens": sum(int(event.get("input_tokens", 0) or 0) for event in model_calls),
        "output_tokens": sum(int(event.get("output_tokens", 0) or 0) for event in model_calls),
        "tool_usage": [{"tool": name, "count": count} for name, count in tool_counter.most_common()],
        "errors": [{"type": name, "count": count} for name, count in error_counter.most_common()],
        "recent_runs": recent_runs,
    }
