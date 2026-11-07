from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.integrations.manufacturing.sqlite_process_diagnostics import (
    SQLiteProcessDiagnosticsAdapter,
)
from app.manufacturing.process_diagnostics.contracts import DiagnosticsQuery

SCHEMA = """
CREATE TABLE process_runs (
    run_id INTEGER PRIMARY KEY,
    lot_id TEXT,
    process_step TEXT,
    equipment_id TEXT,
    run_time TEXT,
    measurement_name TEXT,
    measurement_value REAL,
    measurement_unit TEXT,
    spec_lsl REAL,
    spec_usl REAL
);
"""


@dataclass(frozen=True)
class _Principal:
    tenant_id: str = "demo-fab"
    user_id: str = "local-user"
    roles: tuple[str, ...] = ("analyst",)


def _temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / f"fab-diagnostics-{uuid.uuid4().hex}"
    path.mkdir()
    return path


class DiagnosticsAdapterMathTests(unittest.TestCase):
    def test_capability_query_runs_without_sqlite_math_functions(self):
        """Cpk SQL uses SQRT(); the adapter must not rely on the SQLite build."""
        tmp = _temp_dir()
        self.addCleanup(shutil.rmtree, tmp, True)
        db = tmp / "manufacturing_operations.db"
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA)
        rows = [
            ("CVD", "CVD-01", "2026-01-02T00:00:00+00:00", "thickness", 100.0, "nm", 95.0, 105.0),
            ("CVD", "CVD-01", "2026-01-03T00:00:00+00:00", "thickness", 101.0, "nm", 95.0, 105.0),
            ("CVD", "CVD-01", "2026-01-04T00:00:00+00:00", "thickness", 99.0, "nm", 95.0, 105.0),
        ]
        conn.executemany(
            "INSERT INTO process_runs(process_step, equipment_id, run_time, measurement_name, "
            "measurement_value, measurement_unit, spec_lsl, spec_usl) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

        adapter = SQLiteProcessDiagnosticsAdapter(
            manufacturing_path=db, equipment_path=db, demo_tenant_id="demo-fab"
        )
        snapshot = adapter.fetch(
            DiagnosticsQuery(
                kind="capability",
                start=date(2026, 1, 1),
                end=date(2026, 1, 31),
                process_step="CVD",
            ),
            _Principal(),
        )

        self.assertEqual(len(snapshot.rows), 1)
        row = snapshot.rows[0]
        self.assertEqual(row["process_step"], "CVD")
        self.assertIsNotNone(row["sigma"])
        self.assertIsNotNone(row["cpk"])


if __name__ == "__main__":
    unittest.main()

