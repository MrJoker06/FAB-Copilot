"""Serve the current source against disposable SQLite snapshots for browser tests."""
from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


PROJECT_DIR = Path(__file__).resolve().parents[1]
REFERENCE_DEPARTMENTS = PROJECT_DIR / "data" / "departments"
DEPARTMENT_DATABASES = {
    "FAB_MANUFACTURING_DATABASE_PATH": "manufacturing_operations.db",
    "FAB_EQUIPMENT_DATABASE_PATH": "equipment_engineering.db",
    "FAB_QUALITY_DATABASE_PATH": "yield_quality.db",
    "FAB_KNOWLEDGE_DATABASE_PATH": "process_knowledge.db",
    "FAB_AGENT_DATABASE_PATH": "ai_operations.db",
}
BROWSER_TEST_ADMIN_TOKEN = "browser-test-admin-token"
DEFAULT_PORT = 8899

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def backup_database(source: Path, destination: Path) -> None:
    """Copy an existing SQLite database through a read-only connection."""
    if not source.is_file():
        raise FileNotFoundError(f"browser test reference database is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer)


def browser_test_environment(root: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return deterministic isolated settings without inherited application state."""
    environment = dict(os.environ if environ is None else environ)
    for key in list(environment):
        if key.startswith(("FAB_", "DEEPSEEK_", "AGENT_")):
            environment.pop(key, None)
    departments = root / "departments"
    snapshots = {key: departments / filename for key, filename in DEPARTMENT_DATABASES.items()}
    for destination in snapshots.values():
        backup_database(REFERENCE_DEPARTMENTS / destination.name, destination)
    environment.update({
        "FAB_DATABASE_DIR": str(departments),
        "FAB_DATABASE_PATH": str(root / "legacy.db"),
        **{key: str(value) for key, value in snapshots.items()},
        "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH": str(root / "personal_knowledge"),
        "AGENT_LOG_PATH": str(root / "agent_events.jsonl"),
        "AGENT_RUN_LOG_DIR": str(root / "agent_runs"),
        "FAB_INSTANCE_ID": "playwright-browser-test",
        "FAB_INSTANCE_ROOT": str(root),
        "FAB_SOURCE_ROOT": str(PROJECT_DIR),
        "FAB_WORKSPACE_ENV_FILE": str(root / "missing-workspace.env"),
        "FAB_PROJECT_ENV_FILE": str(root / "missing-project.env"),
        "FAB_ADMIN_API_TOKEN": BROWSER_TEST_ADMIN_TOKEN,
        "FAB_REQUIRE_IDENTITY": "false",
        "FAB_ENTERPRISE_MODE": "true",
        "FAB_DATA_PROVIDER": "synthetic",
        "FAB_DEFAULT_TENANT_ID": "browser-test",
        "FAB_DEFAULT_USER_ID": "browser-test-user",
        "FAB_MOCK_SEED": "20260812",
        "FAB_MODEL_PROVIDER": "browser-test",
        "FAB_MODEL_NAME": "browser-test-model",
        "FAB_MODEL_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "FAB_MODEL_BASE_URL": "http://127.0.0.1:9",
        "DEEPSEEK_BASE_URL": "http://127.0.0.1:9",
        "AGENT_LOG_CONTENT": "metadata",
    })
    return environment


def parse_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=parse_port, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    temporary = Path(tempfile.mkdtemp(prefix="fab-insight-browser-"))
    try:
        print("Preparing isolated browser-test database snapshots...", flush=True)
        environment = browser_test_environment(temporary)
        print("Browser-test database snapshots ready; starting server...", flush=True)
        os.environ.clear()
        os.environ.update(environment)
        os.chdir(PROJECT_DIR)
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
