from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.integrations.manufacturing.sqlite_equipment_health import (
    SQLiteEquipmentHealthAdapter,
)
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthDataError,
    EquipmentHealthQuery,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "user"
    roles: tuple[str, ...] = ("analyst",)


class RealConnectionProxy:
    def __init__(self, connection, failure=""):
        self.connection, self.failure, self.closed, self.callback = (
            connection,
            failure,
            False,
            None,
        )
        self.databases = []

    def execute(self, sql, parameters=()):
        if "ATTACH DATABASE" in sql and self.failure == "attach":
            raise sqlite3.OperationalError("attach failed")
        if "WITH run_stats" in sql:
            names = [row[1] for row in self.connection.execute("PRAGMA database_list")]
            if names != ["main", "equipment"]:
                raise AssertionError(names)
            for statement in (
                "INSERT INTO process_runs VALUES (NULL,NULL,NULL,NULL,NULL,NULL)",
                "INSERT INTO equipment.equipment_events VALUES (NULL,NULL,NULL)",
            ):
                try:
                    self.connection.execute(statement)
                except sqlite3.OperationalError:
                    continue
                raise AssertionError("read-only connection accepted write")
            if self.callback:
                self.assert_timeout()
            if self.failure in {"query", "timeout"}:
                raise sqlite3.OperationalError("interrupted")
        result = self.connection.execute(sql, parameters)
        if sql == "PRAGMA database_list":
            self.databases = [row[1] for row in result.fetchall()]
        return result

    def set_progress_handler(self, callback, count):
        self.callback = callback
        self.connection.set_progress_handler(callback, count)

    def assert_timeout(self):
        if self.failure == "timeout" and self.callback() != 1:
            raise AssertionError("progress did not interrupt")

    def close(self):
        self.closed = True
        self.connection.close()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.manufacturing, self.equipment = root / "m.db", root / "e.db"
        with sqlite3.connect(self.manufacturing) as c:
            c.execute(
                "CREATE TABLE process_runs (equipment_id,process_step,run_time,excursion_code,defect_density,pass_flag)"
            )
            c.execute(
                "INSERT INTO process_runs VALUES ('CMP-01','CMP','2026-01-01',NULL,.1,1)"
            )
        with sqlite3.connect(self.equipment) as c:
            c.execute(
                "CREATE TABLE equipment_events (equipment_id,event_time,duration_minutes)"
            )
        self.query = EquipmentHealthQuery(
            date(2026, 1, 1), date(2026, 1, 2), equipment_id="CMP-01"
        )

    def tearDown(self):
        self.temp.cleanup()

    def adapter(self):
        return SQLiteEquipmentHealthAdapter(
            self.manufacturing, self.equipment, demo_tenant_id="demo"
        )

    def test_close_on_success_attach_query_and_timeout(self):
        real, proxies = sqlite3.connect, []
        for failure in ("", "attach", "query", "timeout"):
            proxies.clear()

            def connect(*a, _failure=failure, **k):
                proxy = RealConnectionProxy(real(*a, **k), _failure)
                proxies.append(proxy)
                return proxy

            monotonic = [0.0, 100.0] if failure == "timeout" else None
            with patch(
                "app.integrations.manufacturing.sqlite_equipment_health.sqlite3.connect",
                connect,
            ):
                timer = (
                    patch(
                        "app.integrations.manufacturing.sqlite_equipment_health.time.monotonic",
                        side_effect=monotonic,
                    )
                    if monotonic
                    else None
                )
                if timer:
                    timer.start()
                try:
                    if failure:
                        with self.assertRaises(EquipmentHealthDataError):
                            self.adapter().fetch(self.query, Principal())
                    else:
                        self.adapter().fetch(self.query, Principal())
                finally:
                    if timer:
                        timer.stop()
            self.assertTrue(proxies[0].closed)

    def test_bool_timeouts_and_schema_failure(self):
        with self.assertRaises(ValueError):
            SQLiteEquipmentHealthAdapter(
                self.manufacturing,
                self.equipment,
                demo_tenant_id="demo",
                busy_timeout_ms=True,
            )
        bad = Path(self.temp.name) / "bad.db"
        sqlite3.connect(bad).close()
        with self.assertRaises(EquipmentHealthDataError):
            SQLiteEquipmentHealthAdapter(
                bad, self.equipment, demo_tenant_id="demo"
            ).fetch(self.query, Principal())

    def test_corrupt_source_metrics_are_data_failure_and_close_connection(self):
        with sqlite3.connect(self.manufacturing) as connection:
            connection.execute("UPDATE process_runs SET pass_flag = 2")
        real_connect = sqlite3.connect
        proxies = []

        def connect(*args, **kwargs):
            proxy = RealConnectionProxy(real_connect(*args, **kwargs))
            proxies.append(proxy)
            return proxy

        with (
            patch(
                "app.integrations.manufacturing.sqlite_equipment_health.sqlite3.connect",
                connect,
            ),
            self.assertRaises(EquipmentHealthDataError),
        ):
            self.adapter().fetch(self.query, Principal())
        self.assertTrue(proxies[0].closed)
        with self.assertRaises(sqlite3.ProgrammingError):
            proxies[0].connection.execute("SELECT 1")
