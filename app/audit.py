from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import subprocess
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_DIR


LOG_PATH = Path(os.getenv("AGENT_LOG_PATH", PROJECT_DIR / "logs" / "agent_events.jsonl"))
if not LOG_PATH.is_absolute():
    LOG_PATH = PROJECT_DIR / LOG_PATH
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
RUN_LOG_DIR = Path(os.getenv("AGENT_RUN_LOG_DIR", PROJECT_DIR / "logs" / "agent"))
if not RUN_LOG_DIR.is_absolute():
    RUN_LOG_DIR = PROJECT_DIR / RUN_LOG_DIR
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_MODE = os.getenv("AGENT_LOG_CONTENT", "metadata").strip().lower()
if CONTENT_MODE not in {"metadata", "redacted", "full"}:
    CONTENT_MODE = "metadata"
SCHEMA_VERSION = "1.1"


def _git_commit() -> str:
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


def emit(event: str, run_id: str, **fields: Any) -> None:
    record = sanitize({
        "timestamp": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "git_commit": GIT_COMMIT,
        "content_mode": CONTENT_MODE,
        "event": event,
        "run_id": run_id,
        **fields,
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
