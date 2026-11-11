"""Business semantics of actual Tool results, shared by diagnostic consumers."""

from __future__ import annotations
from typing import Any
from ..evidence.semantics import EvidenceDescriptor, EvidenceScope

_TOOL_SEMANTICS: dict[str, tuple[str, str, str, str]] = {
    "get_fab_overview": ("metric", "final_wafer_yield", "fab", "fixed_report"),
    "get_yield_trend": ("metric", "final_wafer_yield", "week", "fixed_report"),
    "get_process_pass_rate": (
        "metric",
        "process_run_pass_rate",
        "process",
        "fixed_report",
    ),
    "get_process_capability": (
        "metric",
        "process_capability_cpk",
        "equipment",
        "fixed_report",
    ),
    "get_equipment_health": ("metric", "equipment_health", "equipment", "fixed_report"),
    "get_equipment_productivity": (
        "metric",
        "equipment_productivity",
        "equipment",
        "fixed_report",
    ),
    "get_defect_pareto": ("metric", "defect_pareto", "defect_type", "fixed_report"),
    "get_recent_excursions": ("event", "process_excursion", "event", "fixed_report"),
    "get_sensor_summary": (
        "metric",
        "sensor_summary",
        "equipment_signal",
        "fixed_report",
    ),
    "query_enterprise_data": ("sample", "enterprise_sample", "record", "fixed_report"),
    "search_knowledge": ("document", "knowledge_document", "document", "fixed_report"),
    "get_product_yield_breakdown": (
        "metric",
        "final_wafer_yield",
        "product",
        "fixed_report",
    ),
    "get_equipment_event_timeline": (
        "event",
        "equipment_event",
        "event",
        "fixed_report",
    ),
    "get_equipment_excursion_history": (
        "event",
        "process_excursion_record",
        "event",
        "fixed_report",
    ),
    "get_lot_identity": ("record", "lot_identity", "lot", "fixed_report"),
    "get_lot_process_history": (
        "record",
        "lot_process_history",
        "process_run",
        "fixed_report",
    ),
    "get_lot_excursion_history": (
        "event",
        "process_excursion_record",
        "event",
        "fixed_report",
    ),
    "get_lot_defect_history": (
        "event",
        "defect_record",
        "defect_event",
        "fixed_report",
    ),
    "get_lot_wafer_map_patterns": (
        "record",
        "wafer_map_pattern",
        "wafer",
        "fixed_report",
    ),
}


def descriptor_for_tool(
    source_ref: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    scope_role: str = "primary",
    expected_scope: EvidenceScope | None = None,
    semantic_id: str | None = None,
    grain: str | None = None,
    kind: str | None = None,
    provenance: str | None = None,
) -> EvidenceDescriptor:
    inferred_kind, inferred_semantic_id, inferred_grain, inferred_provenance = (
        _TOOL_SEMANTICS.get(tool, ("unknown", "unknown", "unknown", "unknown"))
    )
    # Query results are only governed when the planner supplied a known template marker.
    if tool == "query_manufacturing_data":
        inferred_provenance = (
            "planner_template"
            if str(arguments.get("_semantic_template", "")).strip()
            else "unknown"
        )
        inferred_kind = "metric" if inferred_provenance != "unknown" else "unknown"
        inferred_semantic_id = str(arguments.get("_semantic_id", "unknown"))
        inferred_grain = str(arguments.get("_semantic_grain", "unknown"))
    return EvidenceDescriptor(
        source_ref=source_ref,
        kind=kind or inferred_kind,
        semantic_id=semantic_id or inferred_semantic_id,
        scope=expected_scope or EvidenceScope.from_arguments(arguments),
        grain=grain or inferred_grain,
        start=str(arguments["start"]) if arguments.get("start") else None,
        end=str(arguments["end"]) if arguments.get("end") else None,
        aggregation="reported",
        filter_provenance=provenance or inferred_provenance,
        scope_role=scope_role,
    )
