"""Read-only, fixed SQLite implementation of production report queries."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.production_reports.contracts import (
    ProductionReportDataError,
    ProductionReportQuery,
    ProductionReportSnapshot,
    ProductionReportTimeoutError,
    production_report_scope,
)


class SQLiteProductionReportsAdapter:
    def __init__(
        self,
        manufacturing_path: Path | None,
        *,
        demo_tenant_id: str,
        busy_timeout_ms: int = 500,
        query_timeout_ms: int = 2000,
    ) -> None:
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > limit
            for value, limit in ((busy_timeout_ms, 10_000), (query_timeout_ms, 30_000))
        ):
            raise ValueError("SQLite timeouts must be finite positive bounded integers")
        self.manufacturing_path = (
            Path(manufacturing_path) if manufacturing_path is not None else None
        )
        self.demo_tenant_id = demo_tenant_id
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms

    @staticmethod
    def _uri(path: Path) -> str:
        return f"{path.resolve().as_uri()}?mode=ro"

    @staticmethod
    def _sql(query: ProductionReportQuery) -> tuple[str, tuple[object, ...]]:
        start, end = query.start.isoformat(), query.end_exclusive.isoformat()
        if query.kind == "overview":
            return (
                """SELECT COUNT(*) AS lots, SUM(wafer_count) AS wafers, SUM(good_wafers) AS good_wafers, ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct, ROUND(AVG(cycle_time_hours), 1) AS avg_cycle_hours, ROUND(AVG(hold_hours), 1) AS avg_hold_hours, SUM(CASE WHEN status = 'Hold' THEN 1 ELSE 0 END) AS held_lots FROM lots WHERE COALESCE(complete_time, start_time) >= ? AND COALESCE(complete_time, start_time) < ?""",
                (start, end),
            )
        if query.kind == "yield":
            product_clause = "AND product = ?" if query.product else ""
            params = (start, end, query.product) if query.product else (start, end)
            return (
                f"""SELECT strftime('%Y-%W', complete_time) AS period, MIN(date(complete_time)) AS week_start, COUNT(*) AS lots, ROUND(100.0 * SUM(good_wafers) / SUM(wafer_count), 2) AS yield_pct, ROUND(AVG(cycle_time_hours), 1) AS cycle_hours FROM lots WHERE complete_time >= ? AND complete_time < ? {product_clause} GROUP BY period ORDER BY period""",
                params,
            )
        clauses = ["run_time >= ?", "run_time < ?", "process_step = ?"]
        params: list[object] = [start, end, query.process_step]
        if query.equipment_id:
            clauses.append("equipment_id = ?")
            params.append(query.equipment_id)
        group = "process_step, equipment_id" if query.equipment_id else "process_step"
        equipment = "equipment_id," if query.equipment_id else "NULL AS equipment_id,"
        return (
            f"""SELECT process_step, {equipment} COUNT(*) AS runs, SUM(CASE WHEN pass_flag THEN 1 ELSE 0 END) AS passed_runs, ROUND(100.0 * AVG(pass_flag), 2) AS pass_pct FROM process_runs WHERE {" AND ".join(clauses)} GROUP BY {group} ORDER BY process_step, equipment_id""",
            tuple(params),
        )

    def _fetch(
        self, query: ProductionReportQuery
    ) -> dict[str, object] | tuple[dict[str, object], ...]:
        path = self.manufacturing_path
        connection: sqlite3.Connection | None = None
        timed = False
        close_failed = False
        started = time.monotonic()
        data: dict[str, object] | tuple[dict[str, object], ...] | None = None
        error: ProductionReportDataError | None = None
        try:
            if path is None or not path.is_file():
                raise ProductionReportDataError(
                    "production-report source is unavailable"
                )
            connection = sqlite3.connect(
                self._uri(path), uri=True, timeout=self.busy_timeout_ms / 1000
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")

            def progress() -> int:
                nonlocal timed
                timed = (time.monotonic() - started) * 1000 > self.query_timeout_ms
                return int(timed)

            connection.set_progress_handler(progress, 1000)
            sql, params = self._sql(query)
            rows = connection.execute(sql, params).fetchall()
            if query.kind == "overview":
                data = dict(rows[0])
                excursion = connection.execute(
                    "SELECT COUNT(*) AS excursions FROM process_runs WHERE run_time >= ? AND run_time < ? AND excursion_code IS NOT NULL",
                    (query.start.isoformat(), query.end_exclusive.isoformat()),
                ).fetchone()
                data.update(
                    excursions=excursion["excursions"],
                    start=query.start.isoformat(),
                    end=query.end.isoformat(),
                )
            else:
                data = tuple(dict(row) for row in rows)
        except ProductionReportDataError:
            error = ProductionReportDataError("production-report source is unavailable")
        except sqlite3.Error:
            if timed:
                error = ProductionReportTimeoutError(
                    "production-report source timed out"
                )
            else:
                error = ProductionReportDataError(
                    "production-report source is unavailable"
                )
        except (OSError, ValueError):
            error = ProductionReportDataError("production-report source is unavailable")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError, ValueError):
                    close_failed = True
        if close_failed:
            raise ProductionReportDataError("production-report source is unavailable")
        if error is not None:
            raise error
        if data is None:
            raise ProductionReportDataError("production-report source is unavailable")
        return data

    def fetch(
        self, query: ProductionReportQuery, principal: ToolPrincipal
    ) -> ProductionReportSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise ProductionReportDataError("production-report source is unavailable")
        return ProductionReportSnapshot(
            query,
            self._fetch(query),
            ToolSource(
                f"sqlite:production-reports:{query.kind}",
                "sqlite-production-reports",
                ToolSourceKind.SQLITE,
                production_report_scope(query, principal),
            ),
        )
