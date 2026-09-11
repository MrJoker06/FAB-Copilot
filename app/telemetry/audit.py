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

from ..config import PROJECT_DIR


LOG_PATH = Path(os.getenv("AGENT_LOG_PATH", PROJECT_DIR / "logs" / "agent_events.jsonl"))
if not LOG_PATH.is_absolute():
    LOG_PATH = PROJECT_DIR / LOG_PATH
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
RUN_LOG_DIR = Path(os.getenv("AGENT_RUN_LOG_DIR", PROJECT_DIR / "logs" / "agent"))
if not RUN_LOG_DIR.is_absolute():
    RUN_LOG_DIR = PROJECT_DIR / RUN_LOG_DIR
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
SCHEMA_VERSION = "1.4"
TRACE_STAGES = ("context", "routing", "retrieval", "tools", "synthesis", "stream")
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


def normalize_audit_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Read old JSONL records through the current additive trace contract."""
    payload = dict(event)
    event_name = str(payload.get("event") or "")
    legacy_schema = payload.get("schema_version")
    if "audit_schema_version" not in payload:
        if event_name in {"turn_decision_created", "turn_decision_degraded"}:
            # OBS-017 fixes an old caller that overwrote the audit schema with
            # the TurnDecision schema.  The original audit version cannot be
            # reconstructed, so preserve it explicitly as legacy.
            payload["audit_schema_version"] = "legacy"
            payload.setdefault("turn_decision_schema_version", legacy_schema or "legacy")
        else:
            payload["audit_schema_version"] = legacy_schema or "legacy"
    if "schema_version" not in payload:
        payload["schema_version"] = payload["audit_schema_version"]

    if event_name == "agent_run_finished":
        # source_count historically meant the number of knowledge source cards,
        # not all evidence references. Keep that interpretation for old readers.
        def safe_count(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        knowledge_count = safe_count(payload.get("knowledge_source_count", payload.get("source_count", 0)))
        tool_count = safe_count(payload.get("tool_evidence_count", 0))
        payload.setdefault("knowledge_source_count", knowledge_count)
        payload.setdefault("tool_evidence_count", tool_count)
        payload.setdefault("total_reference_count", knowledge_count + tool_count)
    return payload


def emit(event: str, run_id: str, *, full_content: Mapping[str, Any] | None = None, **fields: Any) -> None:
    policy = log_content_policy()
    request_id = current_request_id()
    record_fields = {
        **fields,
        **(dict(full_content) if policy["effective_mode"] == "full" and full_content else {}),
    }
    # Core envelope fields are reserved and written last so a component schema
    # cannot silently replace the audit-event schema again.
    record_fields.update({
        "timestamp": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "audit_schema_version": SCHEMA_VERSION,
        "git_commit": GIT_COMMIT,
        "content_mode": policy["effective_mode"],
        "log_policy": policy,
        "event": event,
        "run_id": run_id,
        **({"request_id": request_id} if request_id else {}),
    })
    record = sanitize(record_fields)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
    safe_run_id = "".join(character for character in run_id if character.isalnum() or character in {"-", "_"})[:120] or "unknown"
    day_directory = RUN_LOG_DIR / record["timestamp"][:10]
    with _lock:
        _logger.info(line)
        # Request access events remain in the rotating aggregate log.  Per-request
        # files are reserved for Agent/model/browser executions so admin polling
        # cannot flood the run directory.
        if event not in {"api_request_started", "api_request_finished"}:
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
                        events.append(normalize_audit_event(json.loads(line)))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    events.sort(key=lambda item: item.get("timestamp", ""))
    return events[-max(1, min(limit, 20000)):]


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a stable nearest-rank percentile for bounded monitoring samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(len(ordered) * percentile) - 1))
    return round(ordered[index], 1)


def _run_stage_durations(events: list[dict]) -> dict[str, dict[str, float | None]]:
    """Build exclusive, named stage durations while accepting pre-OBS-017 logs."""
    by_run: dict[str, dict[str, list[float]]] = {}
    explicit: dict[str, set[str]] = {}
    for event in events:
        run_id = str(event.get("run_id") or "")
        if not run_id:
            continue
        values = by_run.setdefault(run_id, {stage: [] for stage in TRACE_STAGES})
        explicit_stages = explicit.setdefault(run_id, set())
        event_name = event.get("event")
        duration = event.get("duration_ms")
        try:
            duration_ms = max(0.0, float(duration)) if duration is not None else None
        except (TypeError, ValueError):
            duration_ms = None

        if event_name == "context_stage_completed" and duration_ms is not None:
            values["context"] = [duration_ms]
            explicit_stages.add("context")
        elif event_name == "routing_stage_completed" and duration_ms is not None:
            values["routing"] = [duration_ms]
            explicit_stages.add("routing")
        elif event_name == "knowledge_retrieval_decided" and duration_ms is not None:
            values["retrieval"] = [duration_ms]
            explicit_stages.add("retrieval")
        elif event_name == "agent_run_finished":
            for stage, field in (("retrieval", "retrieval_duration_ms"), ("tools", "tool_duration_ms")):
                if event.get(field) is None:
                    continue
                try:
                    values[stage] = [max(0.0, float(event[field]))]
                    explicit_stages.add(stage)
                except (TypeError, ValueError):
                    pass
        elif event_name == "model_call_finished" and duration_ms is not None:
            phase = event.get("phase")
            if phase == "contextualization" and "context" not in explicit_stages:
                values["context"].append(duration_ms)
            elif phase in {"agent_loop", "ready_plan_synthesis"}:
                values["synthesis"].append(duration_ms)
        elif event_name == "tool_call_finished" and duration_ms is not None:
            stage = "retrieval" if event.get("tool") == "search_knowledge" else "tools"
            if stage not in explicit_stages:
                values[stage].append(duration_ms)
        elif event_name == "stream_delivery_summary":
            stream_duration = event.get("answer_stream_duration_ms")
            if stream_duration is not None:
                try:
                    values["stream"] = [max(0.0, float(stream_duration))]
                    explicit_stages.add("stream")
                except (TypeError, ValueError):
                    pass

    return {
        run_id: {
            stage: round(sum(values[stage]), 1) if values[stage] else None
            for stage in TRACE_STAGES
        }
        for run_id, values in by_run.items()
    }


def monitoring_summary(hours: int = 24, recent_limit: int = 20) -> dict:
    hours = max(1, min(hours, 24 * 30))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = []
    for raw_event in read_events():
        event = normalize_audit_event(raw_event)
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
    degraded_runs = [event for event in finished if event.get("degraded") is True or event.get("outcome") == "degraded"]
    completed_run_count = sum(
        event.get("status") == "success"
        and not (event.get("degraded") is True or event.get("outcome") == "degraded")
        for event in finished
    )
    context_failures = [event for event in events if event.get("event") == "question_context_resolution_failed"]
    context_failure_reasons = Counter(event.get("failure_reason", "unknown") for event in context_failures)
    durations = [float(event["duration_ms"]) for event in finished if event.get("duration_ms") is not None]
    contextualization_durations = [
        float(event["duration_ms"])
        for event in model_calls
        if event.get("phase") == "contextualization" and event.get("duration_ms") is not None
    ]
    first_answer_durations = [
        float(event["first_answer_ms"])
        for event in events
        if event.get("event") == "stream_delivery_summary" and event.get("first_answer_ms") is not None
    ]
    tool_counter = Counter(event.get("tool", "unknown") for event in tool_calls)
    error_counter = Counter(event.get("error_type", "unknown") for event in events if event.get("status") == "error")

    stage_durations_by_run = _run_stage_durations(events)

    def with_trace_semantics(event: dict) -> dict:
        payload = dict(event)
        payload["stage_durations_ms"] = stage_durations_by_run.get(
            str(event.get("run_id") or ""),
            {stage: None for stage in TRACE_STAGES},
        )
        return payload

    recent_runs = [
        with_trace_semantics(event)
        for event in sorted(finished, key=lambda item: item.get("timestamp", ""), reverse=True)[:max(1, min(recent_limit, 100))]
    ]
    stage_duration_summary = {}
    for stage in TRACE_STAGES:
        values = [
            float(run[stage])
            for run in stage_durations_by_run.values()
            if run.get(stage) is not None
        ]
        stage_duration_summary[stage] = {
            "samples": len(values),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
        }
    return {
        "log_policy": log_content_policy(),
        "window_hours": hours,
        "log_path": str(LOG_PATH),
        "run_log_directory": str(RUN_LOG_DIR),
        "runs": len(finished),
        "success_runs": success_count,
        "completed_run_count": completed_run_count,
        "completed_run_rate_pct": round(100 * completed_run_count / len(finished), 2) if finished else None,
        "degraded_run_count": len(degraded_runs),
        "degraded_run_rate_pct": round(100 * len(degraded_runs) / len(finished), 2) if finished else None,
        "failed_runs": len(finished) - success_count,
        "success_rate_pct": round(100 * success_count / len(finished), 2) if finished else None,
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "p95_duration_ms": _percentile(durations, 0.95),
        "contextualization_duration_p50_ms": _percentile(contextualization_durations, 0.50),
        "contextualization_duration_p95_ms": _percentile(contextualization_durations, 0.95),
        "first_answer_p50_ms": _percentile(first_answer_durations, 0.50),
        "first_answer_p95_ms": _percentile(first_answer_durations, 0.95),
        "stage_durations": stage_duration_summary,
        "model_calls": len(model_calls),
        "tool_calls": len(tool_calls),
        "input_tokens": sum(int(event.get("input_tokens", 0) or 0) for event in model_calls),
        "output_tokens": sum(int(event.get("output_tokens", 0) or 0) for event in model_calls),
        "tool_usage": [{"tool": name, "count": count} for name, count in tool_counter.most_common()],
        "errors": [{"type": name, "count": count} for name, count in error_counter.most_common()],
        "context_failure_count": len(context_failures),
        "context_timeout_count": context_failure_reasons.get("timeout", 0),
        "context_failure_reasons": [{"reason": name, "count": count} for name, count in context_failure_reasons.most_common()],
        "recent_degraded_runs": [
            with_trace_semantics(event)
            for event in sorted(degraded_runs, key=lambda item: item.get("timestamp", ""), reverse=True)[:max(1, min(recent_limit, 100))]
        ],
        "recent_runs": recent_runs,
    }
