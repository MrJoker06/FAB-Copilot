"""Fixed report Tool operations; programmatic calls use no model."""

from __future__ import annotations

from typing import Any

from app.core.storage_identity_ports import storage_identity_bindings
from app.persistence.connection import rows_to_dicts
from app.core.report_dates import timestamp_bounds


def equipment_productivity(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    process_scope = "AND equipment_id = ?" if equipment_id else "AND equipment_id LIKE ?" if process_step else ""
    params: list[Any] = [start, end]
    if equipment_id:
        params.append(equipment_id.upper())
    elif process_step:
        params.append(f"{process_step.upper()}-%")
    with storage_identity_bindings().session_factory() as connection:
        rows = connection.execute(
            f"""SELECT equipment_id,
                      ROUND(SUM(duration_minutes), 1) AS recorded_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END), 1) AS productive_minutes,
                      ROUND(100.0 * SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END)
                            / NULLIF(SUM(duration_minutes), 0), 2) AS productive_pct,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Unscheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS unscheduled_down_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Scheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS scheduled_down_minutes
               FROM equipment_state_intervals
               WHERE start_time >= ? AND start_time < ? {process_scope}
               GROUP BY equipment_id
               ORDER BY productive_pct, unscheduled_down_minutes DESC""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def defect_pareto(
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    process_step: str | None = None,
) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    process_scope = "AND process_step = ?" if process_step else ""
    params: list[Any] = [start, end]
    if process_step:
        params.append(process_step.upper())
    params.append(max(1, min(limit, 25)))
    with storage_identity_bindings().session_factory() as connection:
        rows = connection.execute(
            f"""SELECT defect_type,
                      GROUP_CONCAT(DISTINCT process_step) AS process_steps,
                      SUM(count) AS defect_count,
                      COUNT(DISTINCT lot_id) AS affected_lots,
                      ROUND(100.0 * SUM(count) / SUM(SUM(count)) OVER (), 2) AS share_pct
               FROM defect_records WHERE detected_time >= ? AND detected_time < ? {process_scope}
               GROUP BY defect_type ORDER BY defect_count DESC LIMIT ?""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def recent_excursions(
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    process_clause = "AND process_step = ?" if process_step else ""
    equipment_clause = "AND equipment_id = ?" if equipment_id else ""
    params: list[Any] = [start, end]
    if process_step:
        params.append(process_step.upper())
    if equipment_id:
        params.append(equipment_id.upper())
    params.append(max(1, min(limit, 100)))
    with storage_identity_bindings().session_factory() as connection:
        rows = connection.execute(
            f"""SELECT run_time, lot_id, process_step, equipment_id, excursion_code,
                      thickness_nm, uniformity_pct, defect_density,
                      measurement_name, measurement_value, measurement_unit,
                      spec_lsl, spec_usl
               FROM process_runs
               WHERE run_time >= ? AND run_time < ? AND excursion_code IS NOT NULL
                     {process_clause} {equipment_clause}
               ORDER BY run_time DESC LIMIT ?""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)
