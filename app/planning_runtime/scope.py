from __future__ import annotations

from typing import Any

from ..core.call_scope import call_scope
from ..intent_runtime.contracts import IntentRoute
from app.core.manufacturing_terms import PROCESS_ALIASES
from .contracts import AnalysisScopeContract, ScopeRole

# Backwards-compatible private alias for internal planner callers.
_step_scope = call_scope


def _analysis_scope_contract(route: IntentRoute, resolved: dict[str, Any] | None = None) -> AnalysisScopeContract:
    resolution = route.scope_resolution
    resolved = resolved or {}
    primary_type = "lot" if route.intent == "lot_trace" and resolved.get("lot_id") else "process" if route.intent == "sop_lookup" and route.process_steps else resolution.scope_type
    primary_ids = (str(resolved["lot_id"]).upper(),) if primary_type == "lot" else tuple(route.process_steps) if primary_type == "process" and route.intent == "sop_lookup" else resolution.resolved_ids
    labels: list[str] = list(primary_ids)
    if primary_type == "process":
        for process_step in route.process_steps:
            labels.extend(PROCESS_ALIASES.get(process_step, ()))
        context_only_tools = ("get_fab_overview", "get_yield_trend")
    elif resolution.scope_type == "equipment":
        context_only_tools = ()
    else:
        context_only_tools = ()
    return AnalysisScopeContract(
        primary_scope_type=primary_type,
        primary_scope_ids=primary_ids,
        primary_scope_labels=tuple(dict.fromkeys(str(item) for item in labels if item)),
        context_only_tools=context_only_tools,
    )


def _step_semantics(tool: str, parameters: dict[str, Any], evidence_ids: tuple[str, ...] = ()) -> tuple[str, str, str]:
    """Planner-owned semantics: fixed reports only, no name-specific branches."""
    semantics = {
        "get_fab_overview": ("metric", "final_wafer_yield", "fab"),
        "get_yield_trend": ("metric", "final_wafer_yield", "week"),
        "get_process_pass_rate": ("metric", "process_run_pass_rate", "equipment" if parameters.get("equipment_id") else "process"),
        "get_process_capability": ("metric", "process_capability_cpk", "equipment_distribution"),
        "get_equipment_health": ("metric", "equipment_health", "equipment"),
        "get_equipment_productivity": ("metric", "equipment_productivity", "equipment"),
        "get_defect_pareto": ("metric", "defect_pareto", "defect_type"),
        "get_recent_excursions": ("event", "process_excursion", "event"),
        "get_sensor_summary": ("metric", "sensor_summary", "equipment_signal"),
        "search_knowledge": ("document", "knowledge_document", "document"),
        "get_product_yield_breakdown": ("metric", "final_wafer_yield", "product"),
        "get_equipment_event_timeline": ("event", "equipment_event", "event"),
        "get_equipment_excursion_history": ("event", "process_excursion_record", "event"),
        "get_lot_identity": ("record", "lot_identity", "lot"),
        "get_lot_process_history": ("record", "lot_process_history", "process_run"),
        "get_lot_excursion_history": ("event", "process_excursion_record", "event"),
        "get_lot_defect_history": ("event", "defect_record", "defect_event"),
        "get_lot_wafer_map_patterns": ("record", "wafer_map_pattern", "wafer"),
    }
    if tool == "query_manufacturing_data":
        sql = str(parameters.get("sql", "")).lower()
        if "from wafer_maps" in sql:
            return ("record", "wafer_map_pattern", "wafer")
        if "from defect_records" in sql:
            return ("event", "defect_record", "defect_event")
        if "from process_runs" in sql:
            return ("event" if "excursion_code" in sql else "record", "process_excursion_record" if "excursion_code" in sql else "lot_process_history", "event" if "excursion_code" in sql else "process_run")
        if "from equipment_events" in sql:
            return ("event", "equipment_event", "event")
        if "from lots" in sql and "group by" not in sql:
            return ("record", "lot_identity", "lot")
        # Lots alone do not establish a process-level metric.  The only yield
        # template is product/fab-grain and is therefore background for a
        # process question.
        query = {
            "YLD-02": ("metric", "final_wafer_yield", "product"), "EQP-03": ("event", "equipment_event", "event"),
            "EQP-04": ("record", "process_excursion_record", "process_run"), "LOT-01": ("record", "lot_identity", "lot"),
            "LOT-02": ("record", "lot_process_history", "process_run"), "LOT-03": ("event", "lot_impact_event", "event"),
        }
        return query.get(next(iter(evidence_ids), ""), ("unknown", "unknown", "unknown"))
    return semantics.get(tool, ("unknown", "unknown", "unknown"))


def _target_scope(route: IntentRoute, resolved: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    scope = {"fab_ids": (), "process_steps": (), "equipment_ids": (), "products": (), "lot_ids": (), "wafer_ids": (), "chambers": (), "recipes": ()}
    if route.scope_resolution.scope_type == "fab": scope["fab_ids"] = ("FAB",)
    elif route.intent == "sop_lookup" and route.process_steps: scope["process_steps"] = tuple(route.process_steps)
    elif route.scope_resolution.scope_type == "process": scope["process_steps"] = tuple(route.process_steps)
    elif route.scope_resolution.scope_type == "equipment": scope["equipment_ids"] = tuple(route.equipment_ids)
    elif (route.scope_resolution.scope_type == "lot" or route.intent == "lot_trace") and resolved.get("lot_id"): scope["lot_ids"] = (str(resolved["lot_id"]).upper(),)
    elif route.scope_resolution.scope_type == "product": scope["products"] = tuple(str(item).upper() for item in route.scope_resolution.resolved_ids)
    return scope


def _scope_role(actual: dict[str, tuple[str, ...]], target: dict[str, tuple[str, ...]]) -> ScopeRole:
    # No narrower scope was requested: the question is about the fab as a whole,
    # so nothing can be "broader than the target" and every step is primary.
    if not any(target.values()):
        return "primary"
    return "primary" if actual == target else "context_only"
