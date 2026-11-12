"""Fixed report Tool operations; programmatic calls use no model."""

from __future__ import annotations

from typing import Any

from app.core.storage_identity_ports import storage_identity_bindings
from app.persistence.connection import rows_to_dicts
from app.core.report_dates import timestamp_bounds


def process_capability(start: str | None = None, end: str | None = None, process_step: str | None = None) -> list[dict]:
    start, end_exclusive = timestamp_bounds(start, end)
    clauses = ["run_time >= ?", "run_time < ?", "measurement_value IS NOT NULL"]
    params: list[object] = [start, end_exclusive]
    if process_step:
        clauses.append("process_step = ?")
        params.append(process_step.upper())
    with storage_identity_bindings().session_factory() as connection:
        rows = connection.execute(
            f"""WITH stats AS (
                   SELECT process_step, equipment_id, COUNT(measurement_value) AS samples,
                          AVG(measurement_value) AS mean_value,
                          SQRT(AVG(measurement_value * measurement_value) - AVG(measurement_value) * AVG(measurement_value)) AS sigma,
                          MIN(measurement_value) AS min_value,
                          MAX(measurement_value) AS max_value,
                          MAX(measurement_name) AS metric_name,
                          MAX(measurement_unit) AS metric_unit,
                          MIN(spec_lsl) AS spec_lsl,
                          MAX(spec_usl) AS spec_usl
                   FROM process_runs
                   WHERE {' AND '.join(clauses)}
                   GROUP BY process_step, equipment_id
               )
               SELECT process_step, equipment_id, samples,
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
               FROM stats ORDER BY cpk, process_step, equipment_id""",
            params,
        ).fetchall()
    return rows_to_dicts(rows)


def sensor_summary(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
    signal_name: str | None = None,
) -> list[dict]:
    start, end = timestamp_bounds(start, end)
    clauses = ["sample_time >= ? AND sample_time < ?"]
    params: list[Any] = [start, end]
    for column, value in (("process_step", process_step), ("equipment_id", equipment_id), ("signal_name", signal_name)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value.upper() if column == "process_step" else value)
    with storage_identity_bindings().session_factory() as connection:
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
