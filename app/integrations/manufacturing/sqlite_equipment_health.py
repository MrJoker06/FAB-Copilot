"""Read-only two-store SQLite adapter for the equipment-health pilot."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ...agent_runtime.tools.contracts import (
    ToolPrincipal,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from ...manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthDataError,
    EquipmentHealthQuery,
    EquipmentHealthSnapshot,
    EquipmentHealthTimeoutError,
)


class SQLiteEquipmentHealthAdapter:
    def __init__(
        self,
        manufacturing_path: str | Path,
        equipment_path: str | Path,
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
        self.manufacturing_path = Path(manufacturing_path)
        self.equipment_path = Path(equipment_path)
        self.demo_tenant_id = demo_tenant_id
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms

    @staticmethod
    def _uri(path: Path) -> str:
        return f"{path.resolve().as_uri()}?mode=ro"

    def fetch(
        self, query: EquipmentHealthQuery, principal: ToolPrincipal
    ) -> EquipmentHealthSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise EquipmentHealthDataError("equipment-health source is unavailable")
        if not self.manufacturing_path.is_file() or not self.equipment_path.is_file():
            raise EquipmentHealthDataError("equipment-health source is unavailable")
        connection = None
        started = time.monotonic()
        locally_timed_out = False
        try:
            connection = sqlite3.connect(
                self._uri(self.manufacturing_path),
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
            )
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            connection.execute(
                "ATTACH DATABASE ? AS equipment", (self._uri(self.equipment_path),)
            )
            connection.execute("PRAGMA equipment.query_only = ON")

            def progress() -> int:
                nonlocal locally_timed_out
                locally_timed_out = (
                    time.monotonic() - started
                ) * 1000 > self.query_timeout_ms
                return int(locally_timed_out)

            connection.set_progress_handler(progress, 1000)
            if query.equipment_id:
                run_filter, event_filter, values = (
                    " AND equipment_id = ?",
                    " AND equipment_id = ?",
                    (query.equipment_id,),
                )
                event_values = values
            elif query.process_step:
                run_filter, event_filter = (
                    " AND process_step = ?",
                    " AND equipment_id LIKE ?",
                )
                values, event_values = (
                    (query.process_step,),
                    (f"{query.process_step}-%",),
                )
            else:
                run_filter = event_filter = ""
                values = event_values = ()
            sql = f"""WITH run_stats AS (
                SELECT equipment_id, COUNT(*) AS runs,
                       SUM(CASE WHEN excursion_code IS NOT NULL THEN 1 ELSE 0 END) AS excursions,
                       ROUND(AVG(defect_density), 3) AS avg_defect_density,
                       ROUND(100.0 * AVG(pass_flag), 2) AS pass_pct
                FROM main.process_runs WHERE run_time >= ? AND run_time < ? {run_filter} GROUP BY equipment_id
            ), event_stats AS (
                SELECT equipment_id, COUNT(*) AS events, ROUND(SUM(duration_minutes), 1) AS downtime_minutes
                FROM equipment.equipment_events WHERE event_time >= ? AND event_time < ? {event_filter} GROUP BY equipment_id
            ) SELECT r.equipment_id, r.runs, r.excursions, r.avg_defect_density, r.pass_pct,
                     COALESCE(e.events, 0), COALESCE(e.downtime_minutes, 0)
              FROM run_stats r LEFT JOIN event_stats e USING(equipment_id)"""
            rows = connection.execute(
                sql,
                (
                    query.start.isoformat(),
                    query.end_exclusive.isoformat(),
                    *values,
                    query.start.isoformat(),
                    query.end_exclusive.isoformat(),
                    *event_values,
                ),
            ).fetchall()
            aggregates = tuple(EquipmentHealthAggregate(*row) for row in rows)
        except sqlite3.Error as exc:
            if locally_timed_out:
                raise EquipmentHealthTimeoutError(
                    "equipment-health source timed out"
                ) from exc
            raise EquipmentHealthDataError(
                "equipment-health source is unavailable"
            ) from exc
        except (OSError, ValueError, EquipmentHealthDataError) as exc:
            raise EquipmentHealthDataError(
                "equipment-health source is unavailable"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        scope = ToolScope(
            principal.tenant_id,
            query.start,
            query.end,
            (query.equipment_id,) if query.equipment_id else (),
            (query.process_step,) if query.process_step else (),
            grain="equipment",
        )
        return EquipmentHealthSnapshot(
            query,
            aggregates,
            ToolSource(
                "sqlite:demo-equipment-health",
                "sqlite-equipment-health",
                ToolSourceKind.SQLITE,
                scope,
            ),
        )
