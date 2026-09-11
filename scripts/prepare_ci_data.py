"""Create the disposable synthetic database set required by hosted CI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.persistence.database import db_session, department_paths
from app.model_gateway.registry import ensure_model_catalog
from app.manufacturing.seed import main as seed_main
from scripts import manage_databases


REQUIRED_MODEL_IDS = ("deepseekv4-flash", "deepseekv4-pro")
EXPECTED_END_DATE = "2026-12-25"
EXPECTED_FORECAST_START = "2026-08-11"
EXPECTED_DEPARTMENT_PATHS = {
    "main": PROJECT_DIR / "data" / "departments" / "manufacturing_operations.db",
    "equipment": PROJECT_DIR / "data" / "departments" / "equipment_engineering.db",
    "quality": PROJECT_DIR / "data" / "departments" / "yield_quality.db",
    "knowledge": PROJECT_DIR / "data" / "departments" / "process_knowledge.db",
    "agent": PROJECT_DIR / "data" / "departments" / "ai_operations.db",
}
DATABASE_PATH_ENVIRONMENT = (
    "FAB_DATABASE_PATH", "FAB_DATABASE_DIR", "FAB_MANUFACTURING_DATABASE_PATH",
    "FAB_EQUIPMENT_DATABASE_PATH", "FAB_QUALITY_DATABASE_PATH", "FAB_KNOWLEDGE_DATABASE_PATH",
    "FAB_AGENT_DATABASE_PATH",
)
REQUIRED_MANIFEST_DEPARTMENTS = ("manufacturing", "equipment", "quality", "knowledge", "agent")
REQUIRED_BEYOND_HORIZON_KEYS = (
    "beyond_horizon_lots", "beyond_horizon_process_runs", "beyond_horizon_sensor_readings",
    "beyond_horizon_equipment_state_intervals", "beyond_horizon_equipment_events",
    "beyond_horizon_defect_records", "beyond_horizon_wafer_maps",
)


def _ci_enabled(environ: dict[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("CI", "").strip().lower() == "true"


def reference_database_paths() -> tuple[Path, ...]:
    """Return every department DB whose presence makes fresh CI unsafe."""
    return tuple(department_paths().values())


def reject_database_path_overrides(environ: dict[str, str] | None = None) -> None:
    """CI must seed only the checked-out synthetic database location."""
    values = os.environ if environ is None else environ
    configured = [name for name in DATABASE_PATH_ENVIRONMENT if values.get(name)]
    if configured:
        raise RuntimeError("CI bootstrap rejects FAB database path overrides: " + ", ".join(configured))
    if department_paths() != EXPECTED_DEPARTMENT_PATHS:
        raise RuntimeError("CI bootstrap database paths must be the five default data/departments files")


def reject_existing_reference_databases(paths: tuple[Path, ...] | None = None) -> None:
    paths = paths if paths is not None else reference_database_paths()
    existing = [path for path in paths if path.exists()]
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise RuntimeError(f"CI bootstrap requires a fresh database set; refusing existing files: {rendered}")


def validate_ci_data() -> dict:
    """Verify the generated DBs and their mandatory model catalog rows."""
    report = manage_databases.manifest()
    departments = report.get("departments")
    if not isinstance(departments, dict) or set(departments) != set(REQUIRED_MANIFEST_DEPARTMENTS) or any(
        not isinstance(departments[name], dict) or departments[name].get("quick_check") != "ok"
        for name in REQUIRED_MANIFEST_DEPARTMENTS
    ):
        raise RuntimeError("CI synthetic database manifest validation failed")
    if report.get("governance", {}).get("quick_check") != "ok":
        raise RuntimeError("CI synthetic database governance validation failed")
    governance = report["governance"]
    if governance.get("simulation_metadata_status") != "present":
        raise RuntimeError("CI synthetic database simulation metadata is missing")
    if governance.get("simulation_end_date") != EXPECTED_END_DATE:
        raise RuntimeError("CI synthetic database has an unexpected simulation end date")
    if governance.get("simulation_forecast_start") != EXPECTED_FORECAST_START:
        raise RuntimeError("CI synthetic database has an unexpected simulation forecast start")
    missing_horizon_keys = [key for key in REQUIRED_BEYOND_HORIZON_KEYS if key not in governance]
    if missing_horizon_keys:
        raise RuntimeError("CI synthetic database governance is missing horizon checks: " + ", ".join(missing_horizon_keys))
    beyond_horizon = {key: governance[key] for key in REQUIRED_BEYOND_HORIZON_KEYS if governance[key] != 0}
    if beyond_horizon:
        raise RuntimeError(f"CI synthetic database contains records beyond its horizon: {beyond_horizon}")
    if departments.get("manufacturing", {}).get("tables", {}).get("lots", 0) < 9_000:
        raise RuntimeError("CI synthetic manufacturing database has too few lots")
    if departments.get("equipment", {}).get("tables", {}).get("sensor_readings", 0) < 1_000_000:
        raise RuntimeError("CI synthetic equipment database has too few sensor readings")
    with db_session() as connection:
        rows = connection.execute(
            "SELECT model_id FROM agent.model_catalog WHERE model_id IN (?, ?) AND status = 'published'",
            REQUIRED_MODEL_IDS,
        ).fetchall()
    present = {row[0] for row in rows}
    missing = [model_id for model_id in REQUIRED_MODEL_IDS if model_id not in present]
    if missing:
        raise RuntimeError("CI model catalog is missing published models: " + ", ".join(missing))
    return report


def prepare_ci_data() -> dict:
    if not _ci_enabled():
        raise RuntimeError("refusing CI database bootstrap outside CI=true")
    reject_database_path_overrides()
    reject_existing_reference_databases()
    result = seed_main(["--force", "--days", "730", "--end-date", "2026-12-25"])
    if result != 0:
        raise RuntimeError(f"CI synthetic database generation failed with exit code {result}")
    ensure_model_catalog()
    return validate_ci_data()


def main() -> int:
    report = prepare_ci_data()
    print("CI synthetic database bootstrap validated:", report["governance"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
