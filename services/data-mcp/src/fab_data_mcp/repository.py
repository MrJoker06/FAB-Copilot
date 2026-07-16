from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fab_contracts import ReportRequest

from .database import readonly_session, rows_to_dicts
from .settings import DataMCPSettings


def _range(request: ReportRequest) -> tuple[str, str]:
    end = request.end or date.today()
    start = request.start or (end - timedelta(days=89))
    if start > end:
        raise ValueError("start must not be later than end")
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


class SQLiteManufacturingRepository:
    def __init__(self, settings: DataMCPSettings) -> None:
        self.settings = settings

    def get_fab_overview(self, request: ReportRequest) -> dict[str, Any]:
        start, end = _range(request)
        with readonly_session(self.settings) as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS lots, COALESCE(SUM(wafer_count), 0) AS wafers,
                          ROUND(100.0 * AVG(yield_rate), 2) AS yield_pct,
                          ROUND(AVG(cycle_time_hours), 1) AS avg_cycle_hours,
                          ROUND(AVG(hold_hours), 1) AS avg_hold_hours,
                          SUM(CASE WHEN status = 'Hold' THEN 1 ELSE 0 END) AS held_lots
                   FROM lots WHERE start_time >= ? AND start_time < ?""",
                (start, end),
            ).fetchone()
            excursions = connection.execute(
                """SELECT COUNT(*) FROM process_runs
                   WHERE run_time >= ? AND run_time < ? AND excursion_code IS NOT NULL""",
                (start, end),
            ).fetchone()[0]
        result = dict(row)
        result["excursions"] = excursions
        result["start"] = start
        result["end"] = (date.fromisoformat(end) - timedelta(days=1)).isoformat()
        return result

    def get_yield_trend(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        product_clause = "AND product = ?" if request.product else ""
        params: list[object] = [start, end]
        if request.product:
            params.append(request.product)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                f"""SELECT strftime('%Y-%W', start_time) AS week,
                           ROUND(100.0 * AVG(yield_rate), 2) AS yield_pct,
                           ROUND(AVG(cycle_time_hours), 1) AS cycle_time_hours,
                           COUNT(*) AS lots
                    FROM lots WHERE start_time >= ? AND start_time < ? {product_clause}
                    GROUP BY week ORDER BY week""",
                params,
            ).fetchall()
        return rows_to_dicts(rows)

    def get_equipment_health(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                """WITH run_stats AS (
                       SELECT equipment_id, COUNT(*) AS runs,
                              SUM(CASE WHEN excursion_code IS NOT NULL THEN 1 ELSE 0 END) AS excursions,
                              ROUND(AVG(defect_density), 3) AS avg_defect_density
                       FROM process_runs WHERE run_time >= ? AND run_time < ? GROUP BY equipment_id
                   ), event_stats AS (
                       SELECT equipment_id,
                              ROUND(SUM(CASE WHEN event_type IN ('Unscheduled Down', 'PM')
                                             THEN duration_minutes ELSE 0 END) / 60.0, 1) AS downtime_hours,
                              COUNT(*) AS events
                       FROM equipment_events WHERE event_time >= ? AND event_time < ? GROUP BY equipment_id
                   )
                   SELECT r.equipment_id, r.runs, r.excursions, r.avg_defect_density,
                          COALESCE(e.downtime_hours, 0) AS downtime_hours,
                          COALESCE(e.events, 0) AS events,
                          CASE WHEN r.excursions >= 5 OR COALESCE(e.downtime_hours, 0) >= 10 THEN 'Risk'
                               WHEN r.excursions >= 2 OR COALESCE(e.downtime_hours, 0) >= 4 THEN 'Watch'
                               ELSE 'Healthy' END AS health
                   FROM run_stats r LEFT JOIN event_stats e USING(equipment_id)
                   ORDER BY CASE health WHEN 'Risk' THEN 0 WHEN 'Watch' THEN 1 ELSE 2 END,
                            r.excursions DESC, r.equipment_id""",
                (start, end, start, end),
            ).fetchall()
        return rows_to_dicts(rows)

    def get_equipment_productivity(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                """SELECT equipment_id,
                          ROUND(SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END) / 60.0, 1) AS productive_hours,
                          ROUND(SUM(CASE WHEN semi_e10_state = 'Standby' THEN duration_minutes ELSE 0 END) / 60.0, 1) AS standby_hours,
                          ROUND(SUM(CASE WHEN semi_e10_state = 'Engineering' THEN duration_minutes ELSE 0 END) / 60.0, 1) AS engineering_hours,
                          ROUND(SUM(CASE WHEN semi_e10_state LIKE '%Downtime' THEN duration_minutes ELSE 0 END) / 60.0, 1) AS downtime_hours,
                          ROUND(100.0 * SUM(CASE WHEN semi_e10_state = 'Productive' THEN duration_minutes ELSE 0 END)
                                / NULLIF(SUM(duration_minutes), 0), 2) AS productive_pct
                   FROM equipment_state_intervals WHERE start_time >= ? AND start_time < ?
                   GROUP BY equipment_id ORDER BY productive_pct, equipment_id""",
                (start, end),
            ).fetchall()
        return rows_to_dicts(rows)

    def get_process_capability(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        process_step = request.process_step or "CVD"
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                """WITH stats AS (
                       SELECT equipment_id, COUNT(measurement_value) AS samples,
                              AVG(measurement_value) AS mean_value,
                              SQRT(AVG(measurement_value * measurement_value) - AVG(measurement_value) * AVG(measurement_value)) AS sigma,
                              MIN(measurement_value) AS min_value, MAX(measurement_value) AS max_value,
                              MAX(measurement_name) AS metric_name, MAX(measurement_unit) AS metric_unit,
                              MIN(spec_lsl) AS spec_lsl, MAX(spec_usl) AS spec_usl
                       FROM process_runs
                       WHERE process_step = ? AND run_time >= ? AND run_time < ? AND measurement_value IS NOT NULL
                       GROUP BY equipment_id
                   )
                   SELECT equipment_id, samples, ROUND(mean_value, 3) AS mean_value,
                          ROUND(sigma, 3) AS sigma, ROUND(min_value, 3) AS min_value,
                          ROUND(max_value, 3) AS max_value,
                          ROUND(CASE WHEN spec_lsl IS NULL THEN (spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0))
                                     WHEN spec_usl IS NULL THEN (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0))
                                     ELSE MIN((spec_usl - mean_value) / (3.0 * NULLIF(sigma, 0)),
                                              (mean_value - spec_lsl) / (3.0 * NULLIF(sigma, 0))) END, 2) AS cpk,
                          metric_name, metric_unit, spec_lsl, spec_usl
                   FROM stats ORDER BY cpk""",
                (process_step, start, end),
            ).fetchall()
        return rows_to_dicts(rows)

    def get_defect_pareto(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                """SELECT defect_type, GROUP_CONCAT(DISTINCT process_step) AS process_steps,
                          SUM(count) AS defect_count, COUNT(DISTINCT lot_id) AS affected_lots,
                          ROUND(100.0 * SUM(count) / SUM(SUM(count)) OVER (), 2) AS share_pct
                   FROM defect_records WHERE detected_time >= ? AND detected_time < ?
                   GROUP BY defect_type ORDER BY defect_count DESC LIMIT ?""",
                (start, end, min(request.limit, 25)),
            ).fetchall()
        return rows_to_dicts(rows)

    def get_recent_excursions(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        process_clause = "AND process_step = ?" if request.process_step else ""
        params: list[object] = [start, end]
        if request.process_step:
            params.append(request.process_step)
        params.append(request.limit)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                f"""SELECT run_time, lot_id, process_step, equipment_id, excursion_code,
                           thickness_nm, uniformity_pct, defect_density,
                           measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl
                    FROM process_runs WHERE run_time >= ? AND run_time < ?
                         AND excursion_code IS NOT NULL {process_clause}
                    ORDER BY run_time DESC LIMIT ?""",
                params,
            ).fetchall()
        return rows_to_dicts(rows)

    def get_sensor_summary(self, request: ReportRequest) -> list[dict[str, object]]:
        start, end = _range(request)
        clauses = ["sample_time >= ?", "sample_time < ?"]
        params: list[object] = [start, end]
        for column, value in (
            ("process_step", request.process_step),
            ("equipment_id", request.equipment_id),
            ("signal_name", request.signal_name),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        with readonly_session(self.settings) as connection:
            rows = connection.execute(
                f"""SELECT process_step, equipment_id, signal_name, MAX(signal_unit) AS signal_unit,
                           COUNT(*) AS samples, SUM(is_missing) AS missing_samples,
                           SUM(is_outlier) AS flagged_outliers, ROUND(AVG(signal_value), 5) AS mean_value,
                           ROUND(MIN(signal_value), 5) AS min_value, ROUND(MAX(signal_value), 5) AS max_value
                    FROM sensor_readings WHERE {" AND ".join(clauses)}
                    GROUP BY process_step, equipment_id, signal_name
                    ORDER BY flagged_outliers DESC, missing_samples DESC, process_step, equipment_id LIMIT 100""",
                params,
            ).fetchall()
        return rows_to_dicts(rows)
