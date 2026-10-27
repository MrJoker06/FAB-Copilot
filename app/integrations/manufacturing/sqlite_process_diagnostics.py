"""Read-only SQLite adapter for fixed process diagnostics reports."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.process_diagnostics.contracts import (
    DiagnosticsDataError,
    DiagnosticsQuery,
    DiagnosticsSnapshot,
    DiagnosticsTimeoutError,
    diagnostics_scope,
)


class SQLiteProcessDiagnosticsAdapter:
    """Query one explicit SQLite store per diagnostic kind, without attachment."""

    def __init__(
        self,
        manufacturing_path: Path | None,
        equipment_path: Path | None,
        *,
        demo_tenant_id: str,
        busy_timeout_ms: int = 500,
        query_timeout_ms: int = 2000,
    ) -> None:
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or not 0 < busy_timeout_ms <= 10_000
            or isinstance(query_timeout_ms, bool)
            or not isinstance(query_timeout_ms, int)
            or not 0 < query_timeout_ms <= 30_000
        ):
            raise ValueError("SQLite timeouts must be finite positive bounded integers")
        self.manufacturing_path = (
            Path(manufacturing_path) if manufacturing_path is not None else None
        )
        self.equipment_path = (
            Path(equipment_path) if equipment_path is not None else None
        )
        self.demo_tenant_id = demo_tenant_id
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms

    @staticmethod
    def _uri(path: Path) -> str:
        return f"{path.resolve().as_uri()}?mode=ro"

    @staticmethod
    def _capability_sql(query: DiagnosticsQuery) -> tuple[str, tuple[object, ...]]:
        clauses = ["run_time >= ?", "run_time < ?", "measurement_value IS NOT NULL"]
        params: list[object] = [
            query.start.isoformat(),
            query.end_exclusive.isoformat(),
        ]
        if query.process_step:
            clauses.append("process_step = ?")
            params.append(query.process_step.upper())
        sql = f"""WITH stats AS (
                   SELECT process_step, equipment_id, COUNT(measurement_value) AS samples,
                          AVG(measurement_value) AS mean_value,
                          SQRT(AVG(measurement_value * measurement_value) - AVG(measurement_value) * AVG(measurement_value)) AS sigma,
                          MIN(measurement_value) AS min_value,
                          MAX(measurement_value) AS max_value,
                          MAX(measurement_name) AS metric_name,
                          MAX(measurement_unit) AS metric_unit,
                          MIN(spec_lsl) AS spec_lsl,
                          MAX(spec_usl) AS spec_usl
                   FROM process_runs
                   WHERE {" AND ".join(clauses)}
                   GROUP BY process_step, equipment_id
               )
               SELECT process_step, equipment_id, samples,
                      ROUND(mean_value, 3) AS mean_value,
                      ROUND(sigma, 3) AS sigma,
                      ROUND(min_value, 3) AS min_value,
                      ROUND(max_value, 3) AS max_value,
                      ROUND(CASE
                        WHEN spec_lsl IS NULL THEN (spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0))
                        WHEN spec_usl IS NULL THEN (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0))
                        ELSE MIN((spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0)),
                                 (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0)))
                      END, 2) AS cpk,
                      metric_name, metric_unit, spec_lsl, spec_usl
               FROM stats ORDER BY cpk, process_step, equipment_id"""
        return sql, tuple(params)

    @staticmethod
    def _sensor_sql(query: DiagnosticsQuery) -> tuple[str, tuple[object, ...]]:
        clauses = ["sample_time >= ? AND sample_time < ?"]
        params: list[object] = [
            query.start.isoformat(),
            query.end_exclusive.isoformat(),
        ]
        for column, value in (
            ("process_step", query.process_step),
            ("equipment_id", query.equipment_id),
            ("signal_name", query.signal_name),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value.upper() if column == "process_step" else value)
        sql = f"""SELECT process_step, equipment_id, signal_name, MAX(signal_unit) AS signal_unit,
                       COUNT(*) AS samples,
                       SUM(is_missing) AS missing_samples,
                       SUM(is_outlier) AS flagged_outliers,
                       ROUND(AVG(signal_value), 5) AS mean_value,
                       ROUND(MIN(signal_value), 5) AS min_value,
                       ROUND(MAX(signal_value), 5) AS max_value
                FROM sensor_readings
                WHERE {" AND ".join(clauses)}
                GROUP BY process_step, equipment_id, signal_name
                ORDER BY flagged_outliers DESC, missing_samples DESC, process_step, equipment_id
                LIMIT 100"""
        return sql, tuple(params)

    def _rows(
        self, path: Path | None, query: DiagnosticsQuery
    ) -> tuple[dict[str, object], ...]:
        connection: sqlite3.Connection | None = None
        started = time.monotonic()
        locally_timed_out = False
        rows: tuple[dict[str, object], ...] = ()
        close_failed = False
        try:
            if path is None or not path.is_file():
                raise DiagnosticsDataError("process-diagnostics source is unavailable")
            connection = sqlite3.connect(
                self._uri(path), uri=True, timeout=self.busy_timeout_ms / 1000
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")

            def progress() -> int:
                nonlocal locally_timed_out
                locally_timed_out = (
                    time.monotonic() - started
                ) * 1000 > self.query_timeout_ms
                return int(locally_timed_out)

            connection.set_progress_handler(progress, 1000)
            if query.kind == "capability":
                sql, params = self._capability_sql(query)
            elif query.kind == "sensors":
                sql, params = self._sensor_sql(query)
            else:
                raise DiagnosticsDataError("process-diagnostics source is unavailable")
            rows = tuple(
                dict(row) for row in connection.execute(sql, params).fetchall()
            )
        except DiagnosticsDataError:
            raise
        except sqlite3.Error:
            if locally_timed_out:
                raise DiagnosticsTimeoutError(
                    "process-diagnostics source timed out"
                ) from None
            raise DiagnosticsDataError(
                "process-diagnostics source is unavailable"
            ) from None
        except (OSError, ValueError):
            raise DiagnosticsDataError(
                "process-diagnostics source is unavailable"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError, ValueError):
                    close_failed = True
        if close_failed:
            raise DiagnosticsDataError("process-diagnostics source is unavailable")
        return rows

    def fetch(
        self, query: DiagnosticsQuery, principal: ToolPrincipal
    ) -> DiagnosticsSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise DiagnosticsDataError("process-diagnostics source is unavailable")
        if query.kind == "capability":
            rows = self._rows(self.manufacturing_path, query)
        elif query.kind == "sensors":
            rows = self._rows(self.equipment_path, query)
        else:
            raise DiagnosticsDataError("process-diagnostics source is unavailable")
        return DiagnosticsSnapshot(
            query,
            rows,
            ToolSource(
                f"sqlite:process-diagnostics:{query.kind}",
                "sqlite-process-diagnostics",
                ToolSourceKind.SQLITE,
                diagnostics_scope(query, principal),
            ),
        )
