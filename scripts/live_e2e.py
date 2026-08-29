"""Fail-closed helpers shared by the administrator-authorized live E2E runner."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

LIVE_AUTHORIZATION = "FAB_LIVE_E2E_AUTHORIZED"
LIVE_MODEL_ID = "FAB_LIVE_MODEL_ID"
LIVE_API_KEY = "FAB_MODEL_API_KEY"
LIVE_PROVIDER = "LIVE_PROVIDER"
REPORT_SCHEMA_VERSION = 1
REPORT_KEYS = {"schema_version", "channel", "status", "provider", "model_id", "provider_model", "run_count", "real_model_call_count", "token_totals", "duration_ms", "runs", "model_calls", "degraded_count", "fallback_count"}
RUN_KEYS = {"trace_id", "status", "degraded", "fallback", "input_tokens", "output_tokens", "duration_ms", "phase", "error_type", "failure_reason", "retryable", "will_retry", "attempt"}
SENSITIVE_KEY_PARTS = {"authorization", "api_key", "apikey", "password", "secret", "token", "reasoning_content"}


def require_live_authorization(environ: dict[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    if environment.get(LIVE_AUTHORIZATION) != "true":
        raise RuntimeError(f"live E2E requires {LIVE_AUTHORIZATION}=true")
    model_id = (environment.get(LIVE_MODEL_ID) or "").strip()
    if not model_id:
        raise RuntimeError(f"live E2E requires {LIVE_MODEL_ID}")
    if not (environment.get(LIVE_API_KEY) or environment.get("DEEPSEEK_API_KEY") or "").strip():
        raise RuntimeError("live E2E requires a server-side model API key")
    return model_id


def load_live_catalog_model(database_path: Path, model_id: str, required_capabilities: tuple[str, ...] = ("streaming",)) -> dict[str, Any]:
    """Read only the selected published/verified model from an isolated catalog snapshot."""
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT model_id, provider, provider_model, base_url, status, capabilities_json, compatibility_json "
            "FROM model_catalog WHERE model_id = ?", (model_id,)
        ).fetchone()
    if row is None or row["status"] != "published":
        raise RuntimeError("live E2E selected model is not published")
    try:
        capabilities = json.loads(row["capabilities_json"] or "{}")
        compatibility = json.loads(row["compatibility_json"] or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("live E2E selected model catalog JSON is invalid") from exc
    if compatibility.get("status") != "passed":
        raise RuntimeError("live E2E selected model compatibility is not passed")
    missing = [name for name in required_capabilities if capabilities.get(name) is not True]
    if missing:
        raise RuntimeError("live E2E selected model lacks required capabilities: " + ", ".join(missing))
    return {"model_id": row["model_id"], "provider": row["provider"], "provider_model": row["provider_model"], "base_url": row["base_url"], "capabilities": capabilities}


def sanitized_live_report(model: dict[str, Any], runs: list[dict[str, Any]], started: float, *, status: str, model_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create metadata-only report; source messages and credentials never enter it."""
    safe_runs = [{key: run.get(key) for key in RUN_KEYS if key in run} for run in runs]
    calls = [{key: call.get(key) for key in RUN_KEYS if key in call} for call in (model_calls or [])]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "channel": LIVE_PROVIDER,
        "status": status,
        "provider": model.get("provider", "unknown"),
        "model_id": model["model_id"],
        "provider_model": model["provider_model"],
        "run_count": len(safe_runs),
        "real_model_call_count": len(calls),
        "token_totals": {"input": sum(int(item.get("input_tokens") or 0) for item in calls), "output": sum(int(item.get("output_tokens") or 0) for item in calls)},
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "runs": safe_runs,
        "model_calls": calls,
        "degraded_count": sum(bool(item.get("degraded")) for item in safe_runs),
        "fallback_count": sum(bool(item.get("fallback")) for item in safe_runs),
    }


def enforce_live_bounds(report: dict[str, Any], environ: dict[str, str] | None = None) -> None:
    """Reject accidental cost/time expansion; defaults cover the five-turn matrix."""
    environment = os.environ if environ is None else environ
    max_calls = int(environment.get("FAB_LIVE_E2E_MAX_MODEL_CALLS", "30"))
    max_duration_ms = int(environment.get("FAB_LIVE_E2E_MAX_DURATION_MS", "900000"))
    if report["real_model_call_count"] > max_calls:
        raise RuntimeError("live E2E exceeded maximum model call count")
    if report["duration_ms"] > max_duration_ms:
        raise RuntimeError("live E2E exceeded maximum duration")


def _validate_report_value(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_KEY_PARTS:
                raise ValueError("live E2E report contains sensitive key")
            _validate_report_value(child)
    elif isinstance(value, list):
        for child in value: _validate_report_value(child)


def write_sanitized_report(path: Path, report: dict[str, Any]) -> None:
    if set(report) != REPORT_KEYS or any(set(item) - RUN_KEYS for item in [*report.get("runs", []), *report.get("model_calls", [])]):
        raise ValueError("live E2E report does not match metadata schema")
    _validate_report_value(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan_isolated_artifacts(root: Path, api_key: str) -> None:
    """Reject credentials and hidden reasoning from every temporary artifact."""
    needles = [api_key.encode()] if api_key else []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if any(needle in payload for needle in needles) or b"reasoning_content" in payload:
            raise RuntimeError("live E2E isolated artifact leakage detected")
