"""Live server child: write private metadata for the parent orchestrator only."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

try:
    from live_e2e import load_live_catalog_model, require_live_authorization, scan_isolated_artifacts
    from run_browser_test_server import DEPARTMENT_DATABASES, PROJECT_DIR, REFERENCE_DEPARTMENTS, backup_database, parse_port, run_server
except ModuleNotFoundError:
    from scripts.live_e2e import load_live_catalog_model, require_live_authorization, scan_isolated_artifacts
    from scripts.run_browser_test_server import DEPARTMENT_DATABASES, PROJECT_DIR, REFERENCE_DEPARTMENTS, backup_database, parse_port, run_server


_EXACT_SECRET_ENVIRONMENT_NAMES = frozenset({
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "FAB_MODEL_API_KEY",
    "DEEPSEEK_API_KEY",
    "FAB_ADMIN_API_TOKEN",
    "FAB_PERSONAL_KNOWLEDGE_API_TOKEN",
})
_SECRET_ENVIRONMENT_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def is_secret_environment_name(name: str) -> bool:
    """Return whether an environment variable name denotes a credential."""
    normalized = name.upper()
    return normalized in _EXACT_SECRET_ENVIRONMENT_NAMES or normalized.endswith(_SECRET_ENVIRONMENT_SUFFIXES)


def live_browser_environment(root: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    model_id = require_live_authorization(environment)
    departments = root / "departments"
    snapshots = {key: departments / name for key, name in DEPARTMENT_DATABASES.items()}
    for destination in snapshots.values():
        backup_database(REFERENCE_DEPARTMENTS / destination.name, destination)
    model = load_live_catalog_model(snapshots["FAB_AGENT_DATABASE_PATH"], model_id, ("streaming", "thinking"))
    key = environment.get("FAB_MODEL_API_KEY") or environment.get("DEEPSEEK_API_KEY") or ""
    safe = {name: value for name, value in environment.items() if not is_secret_environment_name(name)}
    retries, retry_base_ms = live_retry_settings(environment)
    safe.update({"FAB_DATABASE_DIR": str(departments), "FAB_DATABASE_PATH": str(root / "legacy.db"), **{key: str(value) for key, value in snapshots.items()}, "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH": str(root / "personal_knowledge"), "FAB_INSTANCE_ID": "live-provider-e2e", "FAB_INSTANCE_ROOT": str(root), "FAB_SOURCE_ROOT": str(PROJECT_DIR), "FAB_WORKSPACE_ENV_FILE": str(root / "missing-workspace.env"), "FAB_PROJECT_ENV_FILE": str(root / "missing-project.env"), "FAB_REQUIRE_IDENTITY": "false", "FAB_DEFAULT_TENANT_ID": "live-provider-e2e", "FAB_DEFAULT_USER_ID": "live-provider-e2e-user", "FAB_DATA_PROVIDER": "synthetic", "FAB_MODEL_PROVIDER": model["provider"], "FAB_MODEL_NAME": model["provider_model"], "FAB_MODEL_BASE_URL": model["base_url"], "FAB_MODEL_API_KEY": key, "MODEL_MAX_RETRIES": str(retries), "MODEL_RETRY_BASE_MS": str(retry_base_ms), "AGENT_LOG_CONTENT": "metadata", "AGENT_LOG_PATH": str(root / "agent_events.jsonl"), "AGENT_RUN_LOG_DIR": str(root / "agent_runs"), "FAB_LIVE_E2E_MODEL_ID": model["model_id"]})
    return safe


def live_retry_settings(environ: dict[str, str]) -> tuple[int, int]:
    """Live-only retry policy; reject malformed/out-of-contract overrides."""
    try:
        retries = int(environ.get("FAB_LIVE_E2E_MODEL_MAX_RETRIES", "4"))
        base_ms = int(environ.get("FAB_LIVE_E2E_MODEL_RETRY_BASE_MS", "1000"))
    except ValueError as exc:
        raise RuntimeError("live E2E retry overrides must be integers") from exc
    if not 0 <= retries <= 4 or not 50 <= base_ms <= 5000:
        raise RuntimeError("live E2E retry overrides are outside application bounds")
    return retries, base_ms


def merge_live_events(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use only this process's fresh audit events, one run record per run_id."""
    calls, by_run = [], {}
    for event in events:
        run_id = str(event.get("run_id") or "")
        if not run_id: continue
        if event.get("event") == "model_call_finished":
            calls.append({key: event.get(key) for key in ("status", "phase", "input_tokens", "output_tokens", "duration_ms", "error_type", "failure_reason", "retryable", "will_retry", "attempt") if key in event} | {"trace_id": run_id})
        if event.get("event") in {"agent_run_finished", "model_local_fallback_activated"}:
            item = by_run.setdefault(run_id, {"trace_id": run_id, "status": event.get("status", "success")})
            item["status"] = event.get("status", item["status"])
            if event.get("mode") == "deterministic-fallback" or event.get("answer_synthesis_status") == "fallback":
                item["fallback"] = True
            if event.get("event") == "agent_run_finished" and event.get("degraded"): item["degraded"] = True
            if event.get("event") == "model_local_fallback_activated": item["fallback"] = True; item["status"] = "error"
    return list(by_run.values()), calls


def _metadata(root: Path, model: dict, started: float, api_key: str) -> dict:
    events = []
    event_log = root / "agent_events.jsonl"
    if event_log.is_file():
        for line in event_log.read_text(encoding="utf-8").splitlines():
            try: event = json.loads(line)
            except json.JSONDecodeError: continue
            events.append(event)
    runs, calls = merge_live_events(events)
    scan_isolated_artifacts(root, api_key)
    return {"model": model, "runs": runs, "model_calls": calls, "duration_ms": round((time.monotonic() - started) * 1000, 1), "leakage_passed": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--port", type=parse_port, default=8900); parser.add_argument("--root", type=Path); args = parser.parse_args(argv)
    parent_owned = args.root is not None
    root = args.root if parent_owned else Path(tempfile.mkdtemp(prefix="fab-insight-live-e2e-")); root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic(); environment = None; model = None
    try:
        environment = live_browser_environment(root)
        model = {"model_id": environment["FAB_LIVE_E2E_MODEL_ID"], "provider_model": environment["FAB_MODEL_NAME"], "provider": environment["FAB_MODEL_PROVIDER"]}
        os.environ.clear(); os.environ.update(environment); os.chdir(PROJECT_DIR); run_server(args.port)
    finally:
        try:
            if not parent_owned and environment is not None and model is not None and os.environ.get("FAB_LIVE_E2E_PRIVATE_REPORT"):
                api_key = os.environ.get("FAB_MODEL_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
                Path(os.environ["FAB_LIVE_E2E_PRIVATE_REPORT"]).write_text(json.dumps(_metadata(root, model, started, api_key)), encoding="utf-8")
        finally:
            if not parent_owned:
                shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__": raise SystemExit(main())
