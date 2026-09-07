from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from ..domain_playbooks import DomainPlaybook, EvidenceRequirement
from ..intent_runtime.contracts import IntentRoute

_LOT_ID_PATTERN = re.compile(
    r"\b(?:LOT[-_ ]?[A-Z0-9]+(?:-[A-Z0-9]+)*|L\d{4,}-\d{3,})\b",
    re.IGNORECASE,
)
_DATE_TOOLS = {
    "get_fab_overview",
    "get_yield_trend",
    "get_equipment_health",
    "get_equipment_productivity",
    "get_process_capability",
    "get_defect_pareto",
    "get_recent_excursions",
    "get_sensor_summary",
    "get_process_pass_rate",
}


def _lot_ids(question: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0).upper().replace(" ", "-") for match in _LOT_ID_PATTERN.finditer(question)))


def _resolved_inputs(question: str, route: IntentRoute, playbook: DomainPlaybook) -> tuple[dict[str, Any], tuple[str, ...]]:
    values: dict[str, Any] = {
        "query": question,
        "time_range": asdict(route.time_range),
    }
    if route.process_steps:
        values["process_step"] = route.process_steps[0]
    if route.equipment_ids:
        values["equipment_id"] = route.equipment_ids[0]
    lot_ids = _lot_ids(question)
    if lot_ids:
        values["lot_id"] = lot_ids[0]
    if route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
        values["product"] = route.scope_resolution.resolved_ids[0]
    missing = tuple(name for name in playbook.required_inputs if not values.get(name))
    return values, missing


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _end_exclusive(route: IntentRoute) -> str:
    return (date.fromisoformat(route.time_range.end) + timedelta(days=1)).isoformat()


def _where_filters(route: IntentRoute, timestamp_column: str, include_equipment: bool = False) -> str:
    clauses = [
        f"{timestamp_column} >= {_sql_literal(route.time_range.start)}",
        f"{timestamp_column} < {_sql_literal(_end_exclusive(route))}",
    ]
    if include_equipment and route.equipment_ids:
        clauses.append(f"equipment_id = {_sql_literal(route.equipment_ids[0])}")
    return " AND ".join(clauses)


def _manufacturing_queries(
    evidence_id: str,
    route: IntentRoute,
    resolved: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    if evidence_id == "YLD-02":
        where = _where_filters(route, "complete_time")
        if route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
            where += f" AND product = {_sql_literal(route.scope_resolution.resolved_ids[0])}"
        return ((
            "产品与技术节点良率分层",
            "SELECT product, technology_nm, COUNT(*) AS lots, SUM(wafer_count) AS wafers, "
            "ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct "
            f"FROM lots WHERE {where} GROUP BY product, technology_nm ORDER BY lots DESC LIMIT 100",
        ),)
    if evidence_id == "EQP-03":
        where = _where_filters(route, "event_time", include_equipment=True)
        return ((
            "设备事件时间线",
            "SELECT equipment_id, event_time, event_type, duration_minutes, severity, reason "
            f"FROM equipment_events WHERE {where} ORDER BY event_time DESC LIMIT 100",
        ),)
    if evidence_id == "EQP-04":
        where = _where_filters(route, "run_time", include_equipment=True)
        process_clause = (
            f" AND process_step = {_sql_literal(route.process_steps[0])}"
            if route.process_steps else ""
        )
        return ((
            "设备关联产品异常",
            "SELECT lot_id, run_time, process_step, equipment_id, excursion_code, "
            "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
            f"FROM process_runs WHERE {where}{process_clause} AND excursion_code IS NOT NULL "
            "ORDER BY run_time DESC LIMIT 100",
        ),)

    lot_id = resolved.get("lot_id")
    if not lot_id:
        return ()
    literal = _sql_literal(str(lot_id))
    if evidence_id == "LOT-01":
        return ((
            "批次身份与状态",
            "SELECT lot_id, product, technology_nm, route, priority, start_time, complete_time, "
            "status, wafer_count, good_wafers, yield_rate, cycle_time_hours, hold_hours "
            f"FROM lots WHERE lot_id = {literal} LIMIT 10",
        ),)
    if evidence_id == "LOT-02":
        return ((
            "批次加工路线",
            "SELECT lot_id, operation_seq, layer_name, process_step, equipment_id, chamber, recipe, "
            "run_time, queue_hours, rework_flag FROM process_runs "
            f"WHERE lot_id = {literal} ORDER BY operation_seq, run_time LIMIT 100",
        ),)
    if evidence_id == "LOT-03":
        return (
            (
                "批次制程异常",
                "SELECT lot_id, operation_seq, run_time, process_step, equipment_id, excursion_code, "
                "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
                f"FROM process_runs WHERE lot_id = {literal} AND excursion_code IS NOT NULL "
                "ORDER BY operation_seq, run_time LIMIT 100",
            ),
            (
                "批次缺陷与处置",
                "SELECT lot_id, detected_time, process_step, defect_type, count, disposition "
                f"FROM defect_records WHERE lot_id = {literal} ORDER BY detected_time LIMIT 100",
            ),
            (
                "批次晶圆图模式",
                "SELECT lot_id, wafer_no, detected_time, process_step, equipment_id, pattern_class, "
                f"tested_dies, failed_dies FROM wafer_maps WHERE lot_id = {literal} "
                "ORDER BY wafer_no LIMIT 100",
            ),
        )
    return ()


def _base_parameters(
    tool: str,
    question: str,
    route: IntentRoute,
    evidence: EvidenceRequirement,
) -> tuple[dict[str, Any], dict[str, str]]:
    parameters: dict[str, Any] = {}
    sources: dict[str, str] = {}
    if tool in _DATE_TOOLS:
        parameters.update({"start": route.time_range.start, "end": route.time_range.end})
        sources.update({"start": "intent_route.time_range", "end": "intent_route.time_range"})
    if tool in {
        "get_process_pass_rate",
        "get_process_capability",
        "get_recent_excursions",
        "get_sensor_summary",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_defect_pareto",
    } and route.process_steps:
        parameters["process_step"] = route.process_steps[0]
        sources["process_step"] = "intent_route.process_steps[0]"
    if tool in {
        "get_process_pass_rate",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_recent_excursions",
        "get_sensor_summary",
    } and route.equipment_ids:
        parameters["equipment_id"] = route.equipment_ids[0]
        sources["equipment_id"] = "intent_route.equipment_ids[0]"
    if tool == "get_recent_excursions":
        parameters["limit"] = 100
        sources["limit"] = "planner.default"
    if tool == "get_defect_pareto":
        parameters["limit"] = 25
        sources["limit"] = "planner.default"
    if tool == "search_knowledge":
        parameters.update({"query": question, "limit": 10})
        sources.update({"query": "user.question", "limit": "planner.default"})
        if route.process_steps:
            parameters["process_step"] = route.process_steps[0]
            sources["process_step"] = "intent_route.process_steps[0]"
        if route.equipment_ids:
            parameters["equipment_id"] = route.equipment_ids[0]
            sources["equipment_id"] = "intent_route.equipment_ids[0]"
        if evidence.evidence_id in {"SOP-01", "SOP-02"}:
            parameters["source_types"] = ["personal", "knowledge"]
            sources["source_types"] = "playbook.evidence_scope"
        elif evidence.evidence_id == "SOP-03":
            parameters["source_types"] = ["case"]
            sources["source_types"] = "playbook.evidence_scope"
        else:
            parameters["source_types"] = ["personal", "knowledge", "case"]
            sources["source_types"] = "playbook.evidence_scope"
    return parameters, sources
