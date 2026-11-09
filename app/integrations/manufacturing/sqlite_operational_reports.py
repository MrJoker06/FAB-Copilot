"""Read-only SQLite adapter for fixed operational manufacturing reports."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...core.sqlite_support import install_sqlite_functions
from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.operational_reports.contracts import (
    OperationalReportDataError,
    OperationalReportQuery,
    OperationalReportSnapshot,
    OperationalReportTimeoutError,
    operational_report_scope,
)


class SQLiteOperationalReportsAdapter:
    """Read one explicit store for each fixed report, without database attachment."""

    def __init__(
        self,
        *,
        equipment_path: Path | None = None,
        quality_path: Path | None = None,
        manufacturing_path: Path | None = None,
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
        self.equipment_path = (
            Path(equipment_path) if equipment_path is not None else None
        )
        self.quality_path = Path(quality_path) if quality_path is not None else None
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
    def _productivity_sql(
        query: OperationalReportQuery,
    ) -> tuple[str, tuple[object, ...]]:
        scope = (
            "AND equipment_id = ?"
            if query.equipment_id
            else "AND equipment_id LIKE ?"
            if query.process_step
            else ""
        )
        params: list[object] = [
            query.start.isoformat(),
            query.end_exclusive.isoformat(),
        ]
        if query.equipment_id:
            params.append(query.equipment_id)
        elif query.process_step:
            params.append(f"{query.process_step}-%")
        return (
            f"""SELECT equipment_id,
                      ROUND(SUM(duration_minutes), 1) AS recorded_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END), 1) AS productive_minutes,
                      ROUND(100.0 * SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END)
                            / NULLIF(SUM(duration_minutes), 0), 2) AS productive_pct,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Unscheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS unscheduled_down_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Scheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS scheduled_down_minutes
               FROM equipment_state_intervals
               WHERE start_time >= ? AND start_time < ? {scope}
               GROUP BY equipment_id
               ORDER BY productive_pct, unscheduled_down_minutes DESC""",
            tuple(params),
        )

    @staticmethod
    def _defects_sql(
        query: OperationalReportQuery,
    ) -> tuple[str, tuple[object, ...]]:
        scope = "AND process_step = ?" if query.process_step else ""
        params: list[object] = [
            query.start.isoformat(),
            query.end_exclusive.isoformat(),
        ]
        if query.process_step:
            params.append(query.process_step)
        params.append(query.limit)
        return (
            f"""SELECT defect_type,
                      GROUP_CONCAT(DISTINCT process_step) AS process_steps,
                      SUM(count) AS defect_count,
                      COUNT(DISTINCT lot_id) AS affected_lots,
                      ROUND(100.0 * SUM(count) / SUM(SUM(count)) OVER (), 2) AS share_pct
               FROM defect_records WHERE detected_time >= ? AND detected_time < ? {scope}
               GROUP BY defect_type ORDER BY defect_count DESC LIMIT ?""",
            tuple(params),
        )

    @staticmethod
    def _excursions_sql(
        query: OperationalReportQuery,
    ) -> tuple[str, tuple[object, ...]]:
        process = "AND process_step = ?" if query.process_step else ""
        equipment = "AND equipment_id = ?" if query.equipment_id else ""
        params: list[object] = [
            query.start.isoformat(),
            query.end_exclusive.isoformat(),
        ]
        if query.process_step:
            params.append(query.process_step)
        if query.equipment_id:
            params.append(query.equipment_id)
        params.append(query.limit)
        return (
            f"""SELECT run_time, lot_id, process_step, equipment_id, excursion_code,
                      thickness_nm, uniformity_pct, defect_density,
                      measurement_name, measurement_value, measurement_unit,
                      spec_lsl, spec_usl
               FROM process_runs
               WHERE run_time >= ? AND run_time < ? AND excursion_code IS NOT NULL
                     {process} {equipment}
               ORDER BY run_time DESC LIMIT ?""",
            tuple(params),
        )

    def _path(self, query: OperationalReportQuery) -> Path | None:
        return {
            "productivity": self.equipment_path,
            "defects": self.quality_path,
            "excursions": self.manufacturing_path,
        }.get(query.kind)

    @classmethod
    def _sql(cls, query: OperationalReportQuery) -> tuple[str, tuple[object, ...]]:
        if query.kind == "productivity":
            return cls._productivity_sql(query)
        if query.kind == "defects":
            return cls._defects_sql(query)
        if query.kind == "excursions":
            return cls._excursions_sql(query)
        raise OperationalReportDataError("operational-report source is unavailable")

    def _rows(
        self, path: Path | None, query: OperationalReportQuery
    ) -> tuple[dict[str, object], ...]:
        connection: sqlite3.Connection | None = None
        started = time.monotonic()
        timed_out = False
        close_failed = False
        rows: tuple[dict[str, object], ...] = ()
        error: OperationalReportDataError | None = None
        try:
            if path is None or not path.is_file():
                raise OperationalReportDataError(
                    "operational-report source is unavailable"
                )
            connection = sqlite3.connect(
                self._uri(path), uri=True, timeout=self.busy_timeout_ms / 1000
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
            sql, params = self._sql(query)
            rows = tuple(
                dict(row) for row in connection.execute(sql, params).fetchall()
            )
        except OperationalReportDataError:
            error = OperationalReportDataError(
                "operational-report source is unavailable"
            )
        except sqlite3.Error:
            error = (
                OperationalReportTimeoutError("operational-report source timed out")
                if timed_out
                else OperationalReportDataError(
                    "operational-report source is unavailable"
                )
            )
        except (OSError, ValueError):
            error = OperationalReportDataError(
                "operational-report source is unavailable"
            )
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError, ValueError):
                    close_failed = True
        if close_failed and not isinstance(error, OperationalReportTimeoutError):
            raise OperationalReportDataError("operational-report source is unavailable")
        if error is not None:
            raise error
        return rows

    def fetch(
        self, query: OperationalReportQuery, principal: ToolPrincipal
    ) -> OperationalReportSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise OperationalReportDataError("operational-report source is unavailable")
        return OperationalReportSnapshot(
            query,
            self._rows(self._path(query), query),
            ToolSource(
                f"sqlite:operational-reports:{query.kind}",
                "sqlite-operational-reports",
                ToolSourceKind.SQLITE,
                operational_report_scope(query, principal),
            ),
        )
