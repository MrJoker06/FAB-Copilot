"""Fixed report Tool operations; programmatic calls use no model."""

from __future__ import annotations

from typing import Any

from app.core.storage_identity_ports import storage_identity_bindings
from app.persistence.connection import rows_to_dicts
from app.core.report_dates import timestamp_bounds


def equipment_health(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    run_scope = "AND equipment_id = ?" if equipment_id else "AND process_step = ?" if process_step else ""
    event_scope = "AND equipment_id = ?" if equipment_id else "AND equipment_id LIKE ?" if process_step else ""
    params: list[Any] = [start, end]
    event_params: list[Any] = [start, end]
    if equipment_id:
        params.append(equipment_id.upper())
        event_params.append(equipment_id.upper())
    elif process_step:
        params.append(process_step.upper())
        event_params.append(f"{process_step.upper()}-%")
    with storage_identity_bindings().session_factory() as connection:
        rows = connection.execute(
            f"""WITH run_stats AS (
                   SELECT equipment_id, COUNT(*) AS runs,
                          SUM(CASE WHEN excursion_code IS NOT NULL THEN 1 ELSE 0 END) AS excursions,
                          ROUND(AVG(defect_density), 3) AS avg_defect_density,
                          ROUND(100.0 * AVG(pass_flag), 2) AS pass_pct
                   FROM process_runs WHERE run_time >= ? AND run_time < ? {run_scope} GROUP BY equipment_id
               ), event_stats AS (
                   SELECT equipment_id, COUNT(*) AS events,
                          ROUND(SUM(duration_minutes), 1) AS downtime_minutes
                   FROM equipment_events WHERE event_time >= ? AND event_time < ? {event_scope} GROUP BY equipment_id
               )
               SELECT r.equipment_id, r.runs, r.excursions, r.avg_defect_density, r.pass_pct,
                      COALESCE(e.events, 0) AS events, COALESCE(e.downtime_minutes, 0) AS downtime_minutes,
                      CASE
                        WHEN r.excursions >= 8 OR COALESCE(e.downtime_minutes, 0) >= 500 THEN 'Critical'
                        WHEN r.excursions >= 3 OR COALESCE(e.downtime_minutes, 0) >= 200 THEN 'Watch'
                        ELSE 'Healthy' END AS health
               FROM run_stats r LEFT JOIN event_stats e USING(equipment_id)
               ORDER BY CASE health WHEN 'Critical' THEN 0 WHEN 'Watch' THEN 1 ELSE 2 END,
                        r.excursions DESC, downtime_minutes DESC""",
            [*params, *event_params],
        ).fetchall()
    return rows_to_dicts(rows)
