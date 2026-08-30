"""Run live E2E with server-only credentials and finalize the safe report."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

try:
    from live_e2e import enforce_live_bounds, require_live_authorization, sanitized_live_report, scan_isolated_artifacts, write_sanitized_report
    from run_browser_test_server import PROJECT_DIR, wait_for_loopback_health
    from run_live_browser_test_server import _metadata, is_secret_environment_name
except ModuleNotFoundError:  # importable from unittest as scripts.run_live_e2e
    from scripts.live_e2e import enforce_live_bounds, require_live_authorization, sanitized_live_report, scan_isolated_artifacts, write_sanitized_report
    from scripts.run_browser_test_server import PROJECT_DIR, wait_for_loopback_health
    from scripts.run_live_browser_test_server import _metadata, is_secret_environment_name

LIVE_REPORT_PATH = PROJECT_DIR / "runtime" / "quality" / "live_e2e_report.json"
EXPECTED_LIVE_RUN_COUNT = 7
PROVIDER_MATRIX_LIVE_RUN_COUNT = 5
LIVE_E2E_TARGET_ENV = "FAB_LIVE_E2E_TARGET"


def resolve_live_target(environ: dict[str, str]) -> tuple[list[str], int]:
    """Return the fixed, allowlisted Live E2E selection and report contract."""
    target = environ.get(LIVE_E2E_TARGET_ENV)
    if target is None or target == "" or target == "full":
        return [], EXPECTED_LIVE_RUN_COUNT
    if target == "provider-matrix":
        return ["--grep", "LIVE-PROVIDER-001"], PROVIDER_MATRIX_LIVE_RUN_COUNT
    raise RuntimeError(f"unsupported {LIVE_E2E_TARGET_ENV}: {target!r}")


def browser_environment(environ: dict[str, str], port: int) -> dict[str, str]:
    safe = {key: value for key, value in environ.items() if not is_secret_environment_name(key)}
    safe["PLAYWRIGHT_LIVE_PORT"] = str(port)
    safe["FAB_LIVE_MODEL_ID"] = environ["FAB_LIVE_MODEL_ID"]
    return safe


def live_matrix_passes(
    report: dict,
    model_calls: list[dict],
    browser_returncode: int,
    *,
    expected_run_count: int = EXPECTED_LIVE_RUN_COUNT,
) -> bool:
    """A retry may fail, but every completed live trace must recover."""
    successful_traces = {str(call.get("trace_id") or "") for call in model_calls if call.get("status") == "success"}
    runs = report["runs"]
    return (
        browser_returncode == 0
        and report["run_count"] == expected_run_count
        and report["real_model_call_count"] > 0
        and report["fallback_count"] == 0
        and report["degraded_count"] == 0
        and all(run.get("status") == "success" and str(run.get("trace_id") or "") in successful_traces for run in runs)
    )


def finalize_report(
    private_path: Path,
    browser_returncode: int,
    api_key: str,
    started: float,
    *,
    report_path: Path = LIVE_REPORT_PATH,
    expected_run_count: int = EXPECTED_LIVE_RUN_COUNT,
) -> dict:
    metadata = json.loads(private_path.read_text(encoding="utf-8")) if private_path.is_file() else {}
    model = metadata.get("model") or {"model_id": "unknown", "provider_model": "unknown", "provider": "unknown"}
    report = sanitized_live_report(model, metadata.get("runs") or [], started, status="passed" if browser_returncode == 0 else "failed", model_calls=metadata.get("model_calls") or [])
    report["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    if not live_matrix_passes(
        report,
        metadata.get("model_calls") or [],
        browser_returncode,
        expected_run_count=expected_run_count,
    ):
        report["status"] = "failed"
    target = report_path
    try:
        enforce_live_bounds(report)
        write_sanitized_report(target, report)
        scan_isolated_artifacts(target.parent, api_key)
    except Exception:
        report["status"] = "failed"
        write_sanitized_report(target, report)
        raise
    if report["status"] != "passed": raise RuntimeError("live E2E browser/provider validation failed")
    return report


def collect_parent_owned_metadata(root: Path, model_id: str, api_key: str, started: float) -> dict:
    """Collect fresh server artifacts after even a forced child termination."""
    from app.model_registry import _decode_model  # local import avoids app config before child setup
    import sqlite3
    database = root / "departments" / "ai_operations.db"
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    if row is None:
        raise RuntimeError("live E2E isolated catalog is missing selected model")
    decoded = _decode_model(row)
    model = {"model_id": decoded["model_id"], "provider": decoded["provider"], "provider_model": decoded["provider_model"]}
    return _metadata(root, model, started, api_key)


def main(argv: list[str] | None = None) -> int:
    del argv
    environment = os.environ.copy(); require_live_authorization(environment)
    playwright_arguments, expected_run_count = resolve_live_target(environment)
    api_key = environment.get("FAB_MODEL_API_KEY") or environment.get("DEEPSEEK_API_KEY") or ""
    port = int(environment.get("PLAYWRIGHT_LIVE_PORT", "8900")); started = time.monotonic(); child = None
    LIVE_REPORT_PATH.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="fab-live-orchestrator-") as temporary:
        private = Path(temporary) / "private_metadata.json"; server_root = Path(temporary) / "server-root"; server_env = environment.copy()
        try:
            child = subprocess.Popen([os.sys.executable, "scripts/run_live_browser_test_server.py", "--port", str(port), "--root", str(server_root)], cwd=PROJECT_DIR, env=server_env)
            if not wait_for_loopback_health(f"http://127.0.0.1:{port}/api/health", timeout_seconds=20, opener=build_opener(ProxyHandler({})).open): raise RuntimeError("live E2E server health check failed")
            browser = subprocess.run(
                ["npx", "playwright", "test", "--config=playwright.live.config.js", *playwright_arguments],
                cwd=PROJECT_DIR,
                env=browser_environment(environment, port),
                check=False,
            )
        finally:
            if child is not None:
                child.terminate()
                try: child.wait(timeout=15)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
        try:
            metadata = collect_parent_owned_metadata(server_root, environment["FAB_LIVE_MODEL_ID"], api_key, started)
            private.write_text(json.dumps(metadata), encoding="utf-8")
        except Exception:
            # Keep finalization authoritative and fail closed even if the child
            # was killed before creating the snapshot/audit files.
            private.write_text("{}", encoding="utf-8")
        finalize_report(
            private,
            browser.returncode if "browser" in locals() else 1,
            api_key,
            started,
            report_path=LIVE_REPORT_PATH,
            expected_run_count=expected_run_count,
        )
    return 0


if __name__ == "__main__": raise SystemExit(main())
