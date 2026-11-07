"""Read-only SQLite adapter for the eight fixed named manufacturing queries."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...core.sqlite_support import install_sqlite_functions
from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.named_queries.contracts import (
    NamedQuery,
    NamedQueryDataError,
    NamedQuerySnapshot,
    NamedQueryTimeoutError,
    named_query_scope,
)


class SQLiteNamedQueryAdapter:
    """Read exactly one explicitly selected store for each fixed query kind."""

    def __init__(
        self,
        *,
        manufacturing_path: Path | None = None,
        equipment_path: Path | None = None,
        quality_path: Path | None = None,
        demo_tenant_id: str,
        busy_timeout_ms: int = 1000,
        query_timeout_ms: int = 1000,
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
        self.equipment_path = (
            Path(equipment_path) if equipment_path is not None else None
        )
        self.quality_path = Path(quality_path) if quality_path is not None else None
        self.demo_tenant_id = demo_tenant_id
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms

    @staticmethod
    def _uri(path: Path) -> str:
        return f"{path.resolve().as_uri()}?mode=ro"

    def _path(self, query: NamedQuery) -> Path | None:
        if query.kind == "equipment_events":
            return self.equipment_path
        if query.kind in {"lot_defects", "lot_wafer_maps"}:
            return self.quality_path
        return self.manufacturing_path

    @staticmethod
    def _sql(query: NamedQuery) -> tuple[str, tuple[object, ...]]:
        if query.kind == "product_yield":
            product = " AND product = ?" if query.product is not None else ""
            params: list[object] = [
                query.start.isoformat(),
                query.end_exclusive.isoformat(),
            ]
            if query.product is not None:
                params.append(query.product)
            return (
                (
                    "SELECT product, technology_nm, COUNT(*) AS lots, SUM(wafer_count) AS wafers, "
                    "ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct "
                    "FROM lots WHERE complete_time >= ? AND complete_time < ?"
                )
                + f"{product} GROUP BY product, technology_nm ORDER BY lots DESC LIMIT 100",
                tuple(params),
            )
        if query.kind == "equipment_events":
            equipment = (
                " AND equipment_id = ?" if query.equipment_id is not None else ""
            )
            params = [query.start.isoformat(), query.end_exclusive.isoformat()]
            if query.equipment_id is not None:
                params.append(query.equipment_id)
            return (
                (
                    "SELECT equipment_id, event_time, event_type, duration_minutes, severity, reason "
                    "FROM equipment_events WHERE event_time >= ? AND event_time < ?"
                )
                + f"{equipment} ORDER BY event_time DESC LIMIT 100",
                tuple(params),
            )
        if query.kind == "equipment_excursions":
            process = " AND process_step = ?" if query.process_step is not None else ""
            equipment = (
                " AND equipment_id = ?" if query.equipment_id is not None else ""
            )
            params = [query.start.isoformat(), query.end_exclusive.isoformat()]
            if query.process_step is not None:
                params.append(query.process_step)
            if query.equipment_id is not None:
                params.append(query.equipment_id)
            return (
                (
                    "SELECT lot_id, run_time, process_step, equipment_id, excursion_code, "
                    "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
                    "FROM process_runs WHERE run_time >= ? AND run_time < ?"
                )
                + f"{process}{equipment} AND excursion_code IS NOT NULL ORDER BY run_time DESC LIMIT 100",
                tuple(params),
            )
        if query.kind == "lot_identity":
            return (
                (
                    "SELECT lot_id, product, technology_nm, route, priority, start_time, complete_time, "
                    "status, wafer_count, good_wafers, yield_rate, cycle_time_hours, hold_hours "
                    "FROM lots WHERE lot_id = ? LIMIT 10"
                ),
                (query.lot_id,),
            )
        if query.kind == "lot_process_history":
            return (
                (
                    "SELECT lot_id, operation_seq, layer_name, process_step, equipment_id, chamber, recipe, "
                    "run_time, queue_hours, rework_flag FROM process_runs "
                    "WHERE lot_id = ? ORDER BY operation_seq, run_time LIMIT 100"
                ),
                (query.lot_id,),
            )
        if query.kind == "lot_excursions":
            return (
                (
                    "SELECT lot_id, operation_seq, run_time, process_step, equipment_id, excursion_code, "
                    "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
                    "FROM process_runs WHERE lot_id = ? AND excursion_code IS NOT NULL "
                    "ORDER BY operation_seq, run_time LIMIT 100"
                ),
                (query.lot_id,),
            )
        if query.kind == "lot_defects":
            return (
                (
                    "SELECT lot_id, detected_time, process_step, defect_type, count, disposition "
                    "FROM defect_records WHERE lot_id = ? ORDER BY detected_time LIMIT 100"
                ),
                (query.lot_id,),
            )
        if query.kind == "lot_wafer_maps":
            return (
                (
                    "SELECT lot_id, wafer_no, detected_time, process_step, equipment_id, pattern_class, "
                    "tested_dies, failed_dies FROM wafer_maps WHERE lot_id = ? "
                    "ORDER BY wafer_no LIMIT 100"
                ),
                (query.lot_id,),
            )
        raise NamedQueryDataError("named-query source is unavailable")

    def _rows(
        self, path: Path | None, query: NamedQuery
    ) -> tuple[dict[str, object], ...]:
        connection: sqlite3.Connection | None = None
        started = time.monotonic()
        timed_out = False
        close_failed = False
        rows: tuple[dict[str, object], ...] = ()
        error: NamedQueryDataError | None = None
        try:
            if path is None or not path.is_file():
                raise NamedQueryDataError("named-query source is unavailable")
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
        except NamedQueryDataError:
            error = NamedQueryDataError("named-query source is unavailable")
        except sqlite3.Error:
            error = (
                NamedQueryTimeoutError("named-query source timed out")
                if timed_out
                else NamedQueryDataError("named-query source is unavailable")
            )
        except TimeoutError:
            error = NamedQueryTimeoutError("named-query source timed out")
        except (OSError, ValueError):
            error = NamedQueryDataError("named-query source is unavailable")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (sqlite3.Error, OSError, ValueError):
                    close_failed = True
        if close_failed and not isinstance(error, NamedQueryTimeoutError):
            raise NamedQueryDataError("named-query source is unavailable")
        if error is not None:
            raise error
        return rows

    def fetch(self, query: NamedQuery, principal: ToolPrincipal) -> NamedQuerySnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise NamedQueryDataError("named-query source is unavailable")
        return NamedQuerySnapshot(
            query,
            self._rows(self._path(query), query),
            ToolSource(
                f"sqlite:named-query/{query.kind}",
                "sqlite-named-query",
                ToolSourceKind.SQLITE,
                named_query_scope(query, principal),
            ),
        )

