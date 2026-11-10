"""Read-only SQLite source for weekly capability trends."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...core.sqlite_support import install_sqlite_functions
from .contracts import (
    CapabilityTrendDataError,
    CapabilityTrendQuery,
    CapabilityTrendSnapshot,
    CapabilityTrendTimeoutError,
    capability_trend_scope,
)


def capability_trend_sql(query: CapabilityTrendQuery) -> tuple[str, tuple[object, ...]]:
    """Return the fixed weekly aggregation; only bound values vary."""
    clauses = ["run_time >= ?", "run_time < ?", "measurement_value IS NOT NULL"]
    params: list[object] = [query.start.isoformat(), query.end_exclusive.isoformat()]
    if query.process_step:
        clauses.append("process_step = ?")
        params.append(query.process_step)
    if query.equipment_id:
        clauses.append("equipment_id = ?")
        params.append(query.equipment_id)
    sql = f"""WITH scoped AS (
               SELECT date(run_time, 'weekday 0', '-6 days') AS week_start,
                      process_step, equipment_id, measurement_value,
                      measurement_name, measurement_unit, spec_lsl, spec_usl
               FROM process_runs
               WHERE {" AND ".join(clauses)}
           ), stats AS (
               SELECT week_start, process_step, equipment_id,
                      COUNT(measurement_value) AS samples,
                      AVG(measurement_value) AS mean_value,
                      SQRT(MAX(0.0, AVG(measurement_value * measurement_value)
                               - AVG(measurement_value) * AVG(measurement_value))) AS sigma,
                      MAX(measurement_name) AS metric_name,
                      MAX(measurement_unit) AS metric_unit,
                      MIN(spec_lsl) AS spec_lsl,
                      MAX(spec_usl) AS spec_usl
               FROM scoped
               GROUP BY week_start, process_step, equipment_id
           )
           SELECT week_start,
                  MAX(week_start, ?) AS period_start,
                  MIN(date(week_start, '+6 days'), ?) AS period_end,
                  process_step, equipment_id, samples,
                  ROUND(mean_value, 3) AS mean_value,
                  ROUND(sigma, 3) AS sigma,
                  ROUND(CASE
                    WHEN spec_lsl IS NULL THEN (spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0))
                    WHEN spec_usl IS NULL THEN (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0))
                    ELSE MIN((spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0)),
                             (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0)))
                  END, 2) AS cpk,
                  metric_name, metric_unit, spec_lsl, spec_usl
           FROM stats ORDER BY process_step, equipment_id, week_start"""
    return sql, (*params, query.start.isoformat(), query.end.isoformat())


class SQLiteCapabilityTrendSource:
    """Query one explicit manufacturing SQLite file in read-only mode."""

    def __init__(
        self,
        manufacturing_path: Path | None,
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
        self.demo_tenant_id = demo_tenant_id
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms

    def _rows(self, query: CapabilityTrendQuery) -> tuple[dict[str, object], ...]:
        path = self.manufacturing_path
        if path is None or not path.is_file():
            raise CapabilityTrendDataError("capability-trend source is unavailable")
        connection: sqlite3.Connection | None = None
        started = time.monotonic()
        timed_out = False
        close_failed = False
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
            )
            install_sqlite_functions(connection)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")

            def progress() -> int:
                nonlocal timed_out
                timed_out = (time.monotonic() - started) * 1000 > self.query_timeout_ms
                return int(timed_out)

            connection.set_progress_handler(progress, 1000)
            sql, params = capability_trend_sql(query)
            rows = tuple(dict(row) for row in connection.execute(sql, params).fetchall())
        except sqlite3.Error:
            if timed_out:
                raise CapabilityTrendTimeoutError(
                    "capability-trend source timed out"
                ) from None
            raise CapabilityTrendDataError(
                "capability-trend source is unavailable"
            ) from None
        except (OSError, ValueError):
            raise CapabilityTrendDataError(
                "capability-trend source is unavailable"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError, ValueError):
                    close_failed = True
        if close_failed:
            raise CapabilityTrendDataError("capability-trend source is unavailable")
        return rows

    def fetch(
        self, query: CapabilityTrendQuery, principal: ToolPrincipal
    ) -> CapabilityTrendSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise CapabilityTrendDataError("capability-trend source is unavailable")
        return CapabilityTrendSnapshot(
            query,
            self._rows(query),
            ToolSource(
                "sqlite:capability-trend",
                "sqlite-capability-trend",
                ToolSourceKind.SQLITE,
                capability_trend_scope(query, principal),
            ),
        )
