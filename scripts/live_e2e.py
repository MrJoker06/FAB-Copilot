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
LIVE_BUDGETS_PATH = Path(__file__).resolve().parent.parent / "evaluations" / "live_e2e_budgets.json"
REPORT_KEYS = {"schema_version", "channel", "status", "target", "commit_sha", "provider", "model_id", "provider_model", "run_count", "real_model_call_count", "token_totals", "startup_ms", "test_ms", "duration_ms", "budget", "budget_status", "runs", "model_calls", "degraded_count", "fallback_count"}
RUN_KEYS = {"trace_id", "status", "degraded", "fallback", "input_tokens", "output_tokens", "duration_ms", "phase", "error_type", "failure_reason", "retryable", "will_retry", "attempt"}
SENSITIVE_KEY_PARTS = {"authorization", "api_key", "apikey", "password", "secret", "token", "reasoning_content"}
BUDGET_KEYS = {"expected_run_count", "max_model_calls", "max_input_tokens", "max_output_tokens", "max_total_tokens", "max_startup_ms", "max_test_ms", "max_duration_ms"}
OVERRIDE_KEYS = {
    "FAB_LIVE_E2E_MAX_MODEL_CALLS": "max_model_calls",
    "FAB_LIVE_E2E_MAX_INPUT_TOKENS": "max_input_tokens",
    "FAB_LIVE_E2E_MAX_OUTPUT_TOKENS": "max_output_tokens",
    "FAB_LIVE_E2E_MAX_TOTAL_TOKENS": "max_total_tokens",
    "FAB_LIVE_E2E_MAX_STARTUP_MS": "max_startup_ms",
    "FAB_LIVE_E2E_MAX_TEST_MS": "max_test_ms",
    "FAB_LIVE_E2E_MAX_DURATION_MS": "max_duration_ms",
}


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


def load_live_budgets(path: Path = LIVE_BUDGETS_PATH) -> dict[str, dict[str, int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("live E2E budget file is invalid") from exc
    if set(payload) != {"schema_version", "targets"} or payload["schema_version"] != 1 or not isinstance(payload["targets"], dict) or set(payload["targets"]) != {"full", "provider-matrix"}:
        raise ValueError("live E2E budget schema is invalid")
    for target, budget in payload["targets"].items():
        if not isinstance(budget, dict) or set(budget) != BUDGET_KEYS or any(type(value) is not int or value <= 0 for value in budget.values()):
            raise ValueError(f"live E2E budget for {target} is invalid")
        if budget["max_total_tokens"] < budget["max_input_tokens"] or budget["max_total_tokens"] < budget["max_output_tokens"]:
            raise ValueError(f"live E2E total token budget for {target} is inconsistent")
        if budget["max_duration_ms"] < budget["max_startup_ms"] or budget["max_duration_ms"] < budget["max_test_ms"]:
            raise ValueError(f"live E2E duration budget for {target} is inconsistent")
    return payload["targets"]


def resolve_live_budget(target: str, environ: dict[str, str] | None = None, *, budgets: dict[str, dict[str, int]] | None = None) -> dict[str, int]:
    environment = os.environ if environ is None else environ
    configured = (budgets or load_live_budgets()).get(target)
    if configured is None:
        raise RuntimeError(f"unsupported live E2E budget target: {target}")
    resolved = dict(configured)
    for environment_name, budget_name in OVERRIDE_KEYS.items():
        raw = environment.get(environment_name)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{environment_name} must be a positive integer") from exc
        if value <= 0 or value > configured[budget_name]:
            raise RuntimeError(f"{environment_name} may only tighten the configured budget")
        resolved[budget_name] = value
    if resolved["max_duration_ms"] < resolved["max_startup_ms"] or resolved["max_duration_ms"] < resolved["max_test_ms"]:
        raise RuntimeError("live E2E tightened duration budget is inconsistent")
    return resolved


def sanitized_live_report(model: dict[str, Any], runs: list[dict[str, Any]], started: float, *, status: str, model_calls: list[dict[str, Any]] | None = None, target: str = "full", commit_sha: str = "unknown", startup_ms: float = 0, test_ms: float = 0, budget: dict[str, int] | None = None) -> dict[str, Any]:
    """Create metadata-only report; source messages and credentials never enter it."""
    safe_runs = [{key: run.get(key) for key in RUN_KEYS if key in run} for run in runs]
    calls = [{key: call.get(key) for key in RUN_KEYS if key in call} for call in (model_calls or [])]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "channel": LIVE_PROVIDER,
        "status": status, "target": target, "commit_sha": commit_sha,
        "provider": model.get("provider", "unknown"),
        "model_id": model["model_id"],
        "provider_model": model["provider_model"],
        "run_count": len(safe_runs),
        "real_model_call_count": len(calls),
        "token_totals": {"input": sum(int(item.get("input_tokens") or 0) for item in calls), "output": sum(int(item.get("output_tokens") or 0) for item in calls), "total": sum(int(item.get("input_tokens") or 0) + int(item.get("output_tokens") or 0) for item in calls)},
        "startup_ms": round(startup_ms, 1), "test_ms": round(test_ms, 1),
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "budget": dict(budget or resolve_live_budget(target)), "budget_status": "pending",
        "runs": safe_runs,
        "model_calls": calls,
        "degraded_count": sum(bool(item.get("degraded")) for item in safe_runs),
        "fallback_count": sum(bool(item.get("fallback")) for item in safe_runs),
    }


def enforce_live_bounds(report: dict[str, Any], environ: dict[str, str] | None = None) -> None:
    """Reject cost or runtime expansion using an allowlisted target budget."""
    budget = resolve_live_budget(str(report.get("target", "full")), environ)
    if report.get("budget") != budget:
        raise RuntimeError("live E2E report budget does not match configured budget")
    limits = {
        "real_model_call_count": ("max_model_calls", "model call count"),
        "startup_ms": ("max_startup_ms", "startup duration"),
        "test_ms": ("max_test_ms", "test duration"),
        "duration_ms": ("max_duration_ms", "total duration"),
    }
    token_totals = report.get("token_totals", {})
    for key, (budget_key, label) in limits.items():
        if isinstance(report.get(key), bool) or not isinstance(report.get(key), (int, float)) or report[key] < 0 or report[key] > budget[budget_key]:
            raise RuntimeError(f"live E2E exceeded maximum {label}")
    for key, budget_key in (("input", "max_input_tokens"), ("output", "max_output_tokens"), ("total", "max_total_tokens")):
        if type(token_totals.get(key)) is not int or token_totals[key] < 0 or token_totals[key] > budget[budget_key]:
            raise RuntimeError(f"live E2E exceeded maximum {key} tokens")
    report["budget_status"] = "passed"


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
    if set(report) != REPORT_KEYS or any(not isinstance(item, dict) or set(item) - RUN_KEYS for item in [*report.get("runs", []), *report.get("model_calls", [])]):
        raise ValueError("live E2E report does not match metadata schema")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION or report.get("channel") != LIVE_PROVIDER or report.get("status") not in {"passed", "failed"} or report.get("target") not in {"full", "provider-matrix"} or not isinstance(report.get("commit_sha"), str):
        raise ValueError("live E2E report has invalid metadata")
    if not isinstance(report.get("budget"), dict) or set(report["budget"]) != BUDGET_KEYS or any(type(value) is not int or value <= 0 for value in report["budget"].values()):
        raise ValueError("live E2E report has invalid budget metadata")
    if report.get("budget_status") not in {"pending", "passed"} or set(report.get("token_totals", {})) != {"input", "output", "total"}:
        raise ValueError("live E2E report has invalid bounded metadata")
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
