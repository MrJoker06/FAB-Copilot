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


def process_capability(start: str | None = None, end: str | None = None, process_step: str = "CVD") -> list[dict]:
    start, end = normalize_range(start, end)
    process_step = process_step.upper()
    with db_session() as connection:
        if process_step == "CVD":
            rows = connection.execute(
                """SELECT equipment_id, COUNT(*) AS samples,
                          ROUND(AVG(thickness_nm), 3) AS mean_value,
                          ROUND(SQRT(AVG(thickness_nm * thickness_nm) - AVG(thickness_nm) * AVG(thickness_nm)), 3) AS sigma,
                          ROUND(MIN(thickness_nm), 3) AS min_value,
                          ROUND(MAX(thickness_nm), 3) AS max_value,
                          ROUND(MIN((105.0 - AVG(thickness_nm)) / (3.0 * NULLIF(SQRT(AVG(thickness_nm * thickness_nm) - AVG(thickness_nm) * AVG(thickness_nm)), 0)),
                                    (AVG(thickness_nm) - 95.0) / (3.0 * NULLIF(SQRT(AVG(thickness_nm * thickness_nm) - AVG(thickness_nm) * AVG(thickness_nm)), 0))), 2) AS cpk,
                          'Thickness nm (LSL 95 / USL 105)' AS metric
                   FROM process_runs
                   WHERE process_step = 'CVD' AND date(run_time) BETWEEN ? AND ?
                   GROUP BY equipment_id ORDER BY cpk""",
                (start, end),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT equipment_id, COUNT(*) AS samples,
                          ROUND(AVG(defect_density), 3) AS mean_value,
                          ROUND(SQRT(AVG(defect_density * defect_density) - AVG(defect_density) * AVG(defect_density)), 3) AS sigma,
                          ROUND(MIN(defect_density), 3) AS min_value,
                          ROUND(MAX(defect_density), 3) AS max_value,
                          ROUND((0.5 - AVG(defect_density)) / (3.0 * NULLIF(SQRT(AVG(defect_density * defect_density) - AVG(defect_density) * AVG(defect_density)), 0)), 2) AS cpk,
                          'Defect density (USL 0.5)' AS metric
                   FROM process_runs
                   WHERE process_step = ? AND date(run_time) BETWEEN ? AND ?
                   GROUP BY equipment_id ORDER BY cpk""",
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


def recent_excursions(start: str | None = None, end: str | None = None, limit: int = 20) -> list[dict]:
    start, end = normalize_range(start, end)
    with db_session() as connection:
        rows = connection.execute(
            """SELECT run_time, lot_id, process_step, equipment_id, excursion_code,
                      thickness_nm, uniformity_pct, defect_density
               FROM process_runs
               WHERE date(run_time) BETWEEN ? AND ? AND excursion_code IS NOT NULL
               ORDER BY run_time DESC LIMIT ?""",
            (start, end, max(1, min(limit, 100))),
        ).fetchall()
    return rows_to_dicts(rows)


ALLOWED_TABLES = {"lots", "process_runs", "equipment_events", "defect_records"}


def safe_select(sql: str) -> list[dict]:
    """Execute a read-only analytical SELECT generated by the model."""
    normalized = re.sub(r"\s+", " ", sql.strip()).rstrip(";")
    if not re.match(r"(?is)^select\b", normalized):
        raise ValueError("只允许 SELECT 查询")
    forbidden = re.compile(r"(?is)\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b")
    if forbidden.search(normalized) or ";" in normalized:
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
