from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fab_data_mcp.settings import DataMCPSettings


@pytest.fixture
def data_mcp_settings(tmp_path: Path) -> DataMCPSettings:
    database_dir = tmp_path / "mcp"
    database_dir.mkdir()
    manufacturing = database_dir / "manufacturing_operations.db"
    equipment = database_dir / "equipment_engineering.db"
    quality = database_dir / "yield_quality.db"

    with sqlite3.connect(manufacturing) as connection:
        connection.executescript(
            """
            CREATE TABLE lots(
                lot_id TEXT PRIMARY KEY, product TEXT, start_time TEXT, status TEXT,
                wafer_count INTEGER, yield_rate REAL, cycle_time_hours REAL, hold_hours REAL
            );
            CREATE TABLE process_runs(
                run_id INTEGER PRIMARY KEY, lot_id TEXT, process_step TEXT, equipment_id TEXT,
                run_time TEXT, excursion_code TEXT, defect_density REAL,
                thickness_nm REAL, uniformity_pct REAL, measurement_name TEXT,
                measurement_value REAL, measurement_unit TEXT, spec_lsl REAL, spec_usl REAL
            );
            INSERT INTO lots VALUES
                ('LOT-1', 'P1', '2026-07-10T00:00:00', 'Complete', 25, 0.94, 80, 0.5),
                ('LOT-2', 'P1', '2026-07-11T00:00:00', 'Hold', 25, 0.88, 96, 3.0);
            INSERT INTO process_runs VALUES
                (1, 'LOT-1', 'CVD', 'CVD-01', '2026-07-10T01:00:00', NULL, 0.1,
                 100, 1.2, 'Thickness', 100, 'nm', 95, 105),
                (2, 'LOT-2', 'CVD', 'CVD-02', '2026-07-11T01:00:00', 'CVD-DRIFT', 0.4,
                 107, 2.2, 'Thickness', 107, 'nm', 95, 105);
            """
        )

    with sqlite3.connect(equipment) as connection:
        connection.executescript(
            """
            CREATE TABLE equipment_events(
                equipment_id TEXT, event_time TEXT, event_type TEXT,
                duration_minutes REAL, severity TEXT, reason TEXT
            );
            CREATE TABLE equipment_state_intervals(
                equipment_id TEXT, chamber TEXT, start_time TEXT,
                duration_minutes REAL, semi_e10_state TEXT, reason TEXT
            );
            CREATE TABLE sensor_readings(
                lot_id TEXT, process_step TEXT, equipment_id TEXT, sample_time TEXT,
                signal_name TEXT, signal_value REAL, signal_unit TEXT,
                is_missing INTEGER, is_outlier INTEGER
            );
            INSERT INTO equipment_events VALUES
                ('CVD-02', '2026-07-11T02:00:00', 'Alarm', 15, 'Medium', 'Drift');
            INSERT INTO equipment_state_intervals VALUES
                ('CVD-01', 'A', '2026-07-10T00:00:00', 1200, 'Productive', 'Production');
            INSERT INTO sensor_readings VALUES
                ('LOT-1', 'CVD', 'CVD-01', '2026-07-10T01:00:00', 'Pressure', 2.1, 'Torr', 0, 0);
            """
        )

    with sqlite3.connect(quality) as connection:
        connection.executescript(
            """
            CREATE TABLE defect_records(
                lot_id TEXT, detected_time TEXT, process_step TEXT,
                defect_type TEXT, count INTEGER, disposition TEXT
            );
            CREATE TABLE wafer_maps(
                lot_id TEXT, wafer_no INTEGER, detected_time TEXT, process_step TEXT,
                equipment_id TEXT, pattern_class TEXT, tested_dies INTEGER, failed_dies INTEGER
            );
            INSERT INTO defect_records VALUES
                ('LOT-2', '2026-07-11T03:00:00', 'CVD', 'Particle', 4, 'Review');
            """
        )

    return DataMCPSettings(
        project_dir=tmp_path,
        database_dir=database_dir,
        service_token="test-service-token",
        query_timeout_seconds=0.5,
    )
