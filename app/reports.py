from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .database import db_session, rows_to_dicts


def default_range() -> tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=89)).isoformat(), end.isoformat()


def normalize_range(start: str | None, end: str | None) -> tuple[str, str]:
    default_start, default_end = default_range()
    try:
        start_value = date.fromisoformat(start or default_start)
        end_value = date.fromisoformat(end or default_end)
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc
    if start_value > end_value:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_value - start_value).days > 730:
        raise ValueError("单次查询范围不能超过 730 天")
    return start_value.isoformat(), end_value.isoformat()


def fab_overview(start: str | None = None, end: str | None = None) -> dict:
    start, end = normalize_range(start, end)
    with db_session() as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS lots,
                      SUM(wafer_count) AS wafers,
                      SUM(good_wafers) AS good_wafers,
                      ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct,
                      ROUND(AVG(cycle_time_hours), 1) AS avg_cycle_hours,
                      ROUND(AVG(hold_hours), 1) AS avg_hold_hours,
                      SUM(CASE WHEN status = 'Hold' THEN 1 ELSE 0 END) AS held_lots
               FROM lots
               WHERE date(COALESCE(complete_time, start_time)) BETWEEN ? AND ?""",
            (start, end),
        ).fetchone()
        excursion = connection.execute(
            """SELECT COUNT(*) AS excursions FROM process_runs
               WHERE date(run_time) BETWEEN ? AND ? AND excursion_code IS NOT NULL""",
            (start, end),
        ).fetchone()
    result = dict(row)
    result["excursions"] = excursion["excursions"]
    result["start"] = start
    result["end"] = end
    return result


def yield_trend(start: str | None = None, end: str | None = None, product: str | None = None) -> list[dict]:
    start, end = normalize_range(start, end)
    product_clause = "AND product = ?" if product else ""
    params: list[Any] = [start, end]
    if product:
        params.append(product)
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT strftime('%Y-%W', complete_time) AS period,
                       MIN(date(complete_time)) AS week_start,
                       COUNT(*) AS lots,
                       ROUND(100.0 * SUM(good_wafers) / SUM(wafer_count), 2) AS yield_pct,
                       ROUND(AVG(cycle_time_hours), 1) AS cycle_hours
                FROM lots
                WHERE date(complete_time) BETWEEN ? AND ? {product_clause}
                GROUP BY period ORDER BY period""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def equipment_health(start: str | None = None, end: str | None = None) -> list[dict]:
    start, end = normalize_range(start, end)
    with db_session() as connection:
        rows = connection.execute(
            """WITH run_stats AS (
                   SELECT equipment_id, COUNT(*) AS runs,
                          SUM(CASE WHEN excursion_code IS NOT NULL THEN 1 ELSE 0 END) AS excursions,
                          ROUND(AVG(defect_density), 3) AS avg_defect_density,
                          ROUND(100.0 * AVG(pass_flag), 2) AS pass_pct
                   FROM process_runs WHERE date(run_time) BETWEEN ? AND ? GROUP BY equipment_id
               ), event_stats AS (
                   SELECT equipment_id, COUNT(*) AS events,
                          ROUND(SUM(duration_minutes), 1) AS downtime_minutes
                   FROM equipment_events WHERE date(event_time) BETWEEN ? AND ? GROUP BY equipment_id
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
            (start, end, start, end),
        ).fetchall()
    return rows_to_dicts(rows)


def equipment_productivity(start: str | None = None, end: str | None = None) -> list[dict]:
    start, end = normalize_range(start, end)
    with db_session() as connection:
        rows = connection.execute(
            """SELECT equipment_id,
                      ROUND(SUM(duration_minutes), 1) AS recorded_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END), 1) AS productive_minutes,
                      ROUND(100.0 * SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END)
                            / NULLIF(SUM(duration_minutes), 0), 2) AS productive_pct,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Unscheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS unscheduled_down_minutes,
                      ROUND(SUM(CASE WHEN semi_e10_state = 'Scheduled Downtime' THEN duration_minutes ELSE 0 END), 1) AS scheduled_down_minutes
               FROM equipment_state_intervals
               WHERE date(start_time) BETWEEN ? AND ?
               GROUP BY equipment_id
               ORDER BY productive_pct, unscheduled_down_minutes DESC""",
            (start, end),
        ).fetchall()
    return rows_to_dicts(rows)


def sensor_summary(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
    signal_name: str | None = None,
) -> list[dict]:
    start, end = normalize_range(start, end)
    clauses = ["date(sample_time) BETWEEN ? AND ?"]
    params: list[Any] = [start, end]
    for column, value in (("process_step", process_step), ("equipment_id", equipment_id), ("signal_name", signal_name)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value.upper() if column == "process_step" else value)
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT process_step, equipment_id, signal_name, MAX(signal_unit) AS signal_unit,
                       COUNT(*) AS samples,
                       SUM(is_missing) AS missing_samples,
                       SUM(is_outlier) AS flagged_outliers,
                       ROUND(AVG(signal_value), 5) AS mean_value,
                       ROUND(MIN(signal_value), 5) AS min_value,
                       ROUND(MAX(signal_value), 5) AS max_value
                FROM sensor_readings
                WHERE {' AND '.join(clauses)}
                GROUP BY process_step, equipment_id, signal_name
                ORDER BY flagged_outliers DESC, missing_samples DESC, process_step, equipment_id
                LIMIT 100""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def process_capability(start: str | None = None, end: str | None = None, process_step: str = "CVD") -> list[dict]:
    start, end = normalize_range(start, end)
    process_step = process_step.upper()
    with db_session() as connection:
        rows = connection.execute(
            """WITH stats AS (
                   SELECT equipment_id, COUNT(measurement_value) AS samples,
                          AVG(measurement_value) AS mean_value,
                          SQRT(AVG(measurement_value * measurement_value) - AVG(measurement_value) * AVG(measurement_value)) AS sigma,
                          MIN(measurement_value) AS min_value,
                          MAX(measurement_value) AS max_value,
                          MAX(measurement_name) AS metric_name,
                          MAX(measurement_unit) AS metric_unit,
                          MIN(spec_lsl) AS spec_lsl,
                          MAX(spec_usl) AS spec_usl
                   FROM process_runs
                   WHERE process_step = ? AND date(run_time) BETWEEN ? AND ?
                         AND measurement_value IS NOT NULL
                   GROUP BY equipment_id
               )
               SELECT equipment_id, samples,
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
               FROM stats ORDER BY cpk""",
            (process_step, start, end),
        ).fetchall()
    return rows_to_dicts(rows)


def defect_pareto(start: str | None = None, end: str | None = None, limit: int = 10) -> list[dict]:
    start, end = normalize_range(start, end)
    with db_session() as connection:
        rows = connection.execute(
            """SELECT defect_type,
                      GROUP_CONCAT(DISTINCT process_step) AS process_steps,
                      SUM(count) AS defect_count,
                      COUNT(DISTINCT lot_id) AS affected_lots,
                      ROUND(100.0 * SUM(count) / SUM(SUM(count)) OVER (), 2) AS share_pct
               FROM defect_records WHERE date(detected_time) BETWEEN ? AND ?
               GROUP BY defect_type ORDER BY defect_count DESC LIMIT ?""",
            (start, end, max(1, min(limit, 25))),
        ).fetchall()
    return rows_to_dicts(rows)


def recent_excursions(
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
    process_step: str | None = None,
) -> list[dict]:
    start, end = normalize_range(start, end)
    process_clause = "AND process_step = ?" if process_step else ""
    params: list[Any] = [start, end]
    if process_step:
        params.append(process_step.upper())
    params.append(max(1, min(limit, 100)))
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT run_time, lot_id, process_step, equipment_id, excursion_code,
                      thickness_nm, uniformity_pct, defect_density,
                      measurement_name, measurement_value, measurement_unit,
                      spec_lsl, spec_usl
               FROM process_runs
               WHERE date(run_time) BETWEEN ? AND ? AND excursion_code IS NOT NULL
                     {process_clause}
               ORDER BY run_time DESC LIMIT ?""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


ALLOWED_TABLES = {
    "lots", "process_runs", "equipment_events", "defect_records",
    "sensor_readings", "equipment_state_intervals", "wafer_maps",
}


def safe_select(sql: str) -> list[dict]:
    """Execute a read-only analytical SELECT generated by the model."""
    normalized = re.sub(r"\s+", " ", sql.strip()).rstrip(";")
    if not re.match(r"(?is)^select\b", normalized):
        raise ValueError("只允许 SELECT 查询")
    forbidden = re.compile(r"(?is)\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b")
    hidden_ground_truth = re.compile(r"(?i)\b(simulation_scenarios|scenario_id|root_cause)\b")
    if forbidden.search(normalized) or hidden_ground_truth.search(normalized) or ";" in normalized:
        raise ValueError("查询包含不允许的语句")
    referenced = set(re.findall(r"(?i)\b(?:from|join)\s+([a-z_][a-z0-9_]*)", normalized))
    if not referenced or not referenced.issubset(ALLOWED_TABLES):
        raise ValueError("查询只能访问制造数据白名单表")
    if not re.search(r"(?i)\blimit\s+\d+\b", normalized):
        normalized += " LIMIT 100"
    with db_session() as connection:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(normalized).fetchmany(100)
    return rows_to_dicts(rows)


def report_bundle(start: str | None = None, end: str | None = None) -> dict:
    start, end = normalize_range(start, end)
    return {
        "overview": fab_overview(start, end),
        "yield_trend": yield_trend(start, end),
        "equipment": equipment_health(start, end),
        "defects": defect_pareto(start, end, 8),
        "excursions": recent_excursions(start, end, 12),
    }
