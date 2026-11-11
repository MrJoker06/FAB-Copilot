"""Fixed report Tool operations; programmatic calls use no model."""

from __future__ import annotations

from typing import Any

from app.persistence import database
from app.core.report_dates import normalize_range, timestamp_bounds


def fab_overview(start: str | None = None, end: str | None = None) -> dict:
    start, end = normalize_range(start, end)
    _, end_exclusive = timestamp_bounds(start, end)
    with database.db_session() as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS lots,
                      SUM(wafer_count) AS wafers,
                      SUM(good_wafers) AS good_wafers,
                      ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct,
                      ROUND(AVG(cycle_time_hours), 1) AS avg_cycle_hours,
                      ROUND(AVG(hold_hours), 1) AS avg_hold_hours,
                      SUM(CASE WHEN status = 'Hold' THEN 1 ELSE 0 END) AS held_lots
               FROM lots
               WHERE COALESCE(complete_time, start_time) >= ?
                     AND COALESCE(complete_time, start_time) < ?""",
            (start, end_exclusive),
        ).fetchone()
        excursion = connection.execute(
            """SELECT COUNT(*) AS excursions FROM process_runs
               WHERE run_time >= ? AND run_time < ? AND excursion_code IS NOT NULL""",
            (start, end_exclusive),
        ).fetchone()
    result = dict(row)
    result["excursions"] = excursion["excursions"]
    result["start"] = start
    result["end"] = end
    return result


def yield_trend(start: str | None = None, end: str | None = None, product: str | None = None) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    product_clause = "AND product = ?" if product else ""
    params: list[Any] = [start, end]
    if product:
        params.append(product)
    with database.db_session() as connection:
        rows = connection.execute(
            f"""SELECT strftime('%Y-%W', complete_time) AS period,
                       MIN(date(complete_time)) AS week_start,
                       COUNT(*) AS lots,
                       ROUND(100.0 * SUM(good_wafers) / SUM(wafer_count), 2) AS yield_pct,
                       ROUND(AVG(cycle_time_hours), 1) AS cycle_hours
                FROM lots
                WHERE complete_time >= ? AND complete_time < ? {product_clause}
                GROUP BY period ORDER BY period""",
            params,
        ).fetchall()
    return database.rows_to_dicts(rows)


def process_pass_rate(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> list[dict]:
    """Return process-run pass rate, deliberately distinct from final wafer yield."""
    if not process_step:
        raise ValueError("制程运行通过率必须指定 process_step")
    start, end = timestamp_bounds(start, end)
    clauses = ["run_time >= ?", "run_time < ?", "process_step = ?"]
    params: list[Any] = [start, end, process_step.upper()]
    if equipment_id:
        clauses.append("equipment_id = ?")
        params.append(equipment_id.upper())
    with database.db_session() as connection:
        group_by = "process_step, equipment_id" if equipment_id else "process_step"
        equipment_column = "equipment_id," if equipment_id else "NULL AS equipment_id,"
        rows = connection.execute(
            f"""SELECT process_step, {equipment_column} COUNT(*) AS runs,
                       SUM(CASE WHEN pass_flag THEN 1 ELSE 0 END) AS passed_runs,
                       ROUND(100.0 * AVG(pass_flag), 2) AS pass_pct
                FROM process_runs WHERE {' AND '.join(clauses)}
                GROUP BY {group_by}
                ORDER BY process_step, equipment_id""",
            params,
        ).fetchall()
    return database.rows_to_dicts(rows)
