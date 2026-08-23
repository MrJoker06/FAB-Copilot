"""Deterministic semantics for manufacturing evidence and answer claims.

This is deliberately a small in-process contract, not a semantic-layer service.
It keeps a tool result's metric, scope, grain and provenance attached to the
call so that a broad result cannot be presented as a narrower conclusion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class ScopeRelation(StrEnum):
    EXACT = "exact"
    NARROWER = "narrower"
    BROADER = "broader"
    OVERLAPPING = "overlapping"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceScope:
    fab_ids: tuple[str, ...] = ()
    process_steps: tuple[str, ...] = ()
    equipment_ids: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    lot_ids: tuple[str, ...] = ()
    wafer_ids: tuple[str, ...] = ()
    chambers: tuple[str, ...] = ()
    recipes: tuple[str, ...] = ()

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any]) -> "EvidenceScope":
        def values(*keys: str) -> tuple[str, ...]:
            raw = next((arguments[key] for key in keys if arguments.get(key) not in (None, "")), ())
            if not isinstance(raw, (list, tuple, set)):
                raw = (raw,) if raw else ()
            return tuple(sorted({str(value).strip().upper() for value in raw if str(value).strip()}))
        return cls(
            process_steps=values("process_step", "process_steps"),
            equipment_ids=values("equipment_id", "equipment_ids"),
            products=values("product", "products"),
            lot_ids=values("lot_id", "lot_ids"),
            wafer_ids=values("wafer_id", "wafer_ids"),
            chambers=values("chamber", "chambers"),
            recipes=values("recipe", "recipes"),
        )

    def is_empty(self) -> bool:
        return not any(vars(self).values())


@dataclass(frozen=True)
class EvidenceDescriptor:
    source_ref: str
    kind: Literal["metric", "record", "event", "document", "sample", "unknown"] = "unknown"
    semantic_id: str = "unknown"
    scope: EvidenceScope = field(default_factory=EvidenceScope)
    grain: str = "unknown"
    start: str | None = None
    end: str | None = None
    aggregation: str = "unknown"
    filter_provenance: str = "unknown"
    scope_role: str = "primary"


def scope_relation(evidence: EvidenceScope, claim: EvidenceScope) -> ScopeRelation:
    """Compare multi-dimensional scope sets without special-casing process names."""
    if claim.is_empty():
        return ScopeRelation.UNKNOWN
    if evidence.is_empty():
        return ScopeRelation.UNKNOWN
    narrower = broader = False
    for name in vars(claim):
        wanted = set(getattr(claim, name))
        actual = set(getattr(evidence, name))
        if not wanted:
            continue
        if not actual:
            return ScopeRelation.UNKNOWN
        if actual.isdisjoint(wanted):
            return ScopeRelation.DISJOINT
        if actual < wanted:
            narrower = True
        elif actual > wanted:
            broader = True
        elif actual != wanted:
            return ScopeRelation.OVERLAPPING
    # Extra dimensions make evidence narrower: one equipment in a process is
    # not evidence for the process population, and one lot is not a product.
    if any(getattr(evidence, name) and not getattr(claim, name) for name in vars(claim)):
        narrower = True
    if narrower and broader:
        return ScopeRelation.OVERLAPPING
    if narrower:
        return ScopeRelation.NARROWER
    if broader:
        return ScopeRelation.BROADER
    return ScopeRelation.EXACT


def supports_claim(evidence: EvidenceDescriptor, *, kind: str, semantic_id: str,
                   scope: EvidenceScope, grain: str, start: str | None = None, end: str | None = None, claim_role: str = "primary") -> bool:
    """Fail closed for unknown provenance/semantics and incompatible scope/time."""
    if evidence.filter_provenance == "unknown" or evidence.kind == "unknown" or evidence.grain == "unknown":
        return False
    if kind and evidence.kind != kind:
        return False
    if semantic_id and evidence.semantic_id != semantic_id:
        return False
    if not grain or grain != evidence.grain:
        return False
    if scope_relation(evidence.scope, scope) is not ScopeRelation.EXACT:
        return False
    # Statistical claims must name the same bounded time period as evidence.
    if bool(evidence.start) != bool(start) or bool(evidence.end) != bool(end):
        return False
    if start and start != evidence.start:
        return False
    if end and end != evidence.end:
        return False
    return evidence.scope_role != "context_only" or claim_role == "background"


_TOOL_SEMANTICS: dict[str, tuple[str, str, str, str]] = {
    "get_fab_overview": ("metric", "final_wafer_yield", "fab", "fixed_report"),
    "get_yield_trend": ("metric", "final_wafer_yield", "week", "fixed_report"),
    "get_process_pass_rate": ("metric", "process_run_pass_rate", "process", "fixed_report"),
    "get_process_capability": ("metric", "process_capability_cpk", "equipment", "fixed_report"),
    "get_equipment_health": ("metric", "equipment_health", "equipment", "fixed_report"),
    "get_equipment_productivity": ("metric", "equipment_productivity", "equipment", "fixed_report"),
    "get_defect_pareto": ("metric", "defect_pareto", "defect_type", "fixed_report"),
    "get_recent_excursions": ("event", "process_excursion", "event", "fixed_report"),
    "get_sensor_summary": ("metric", "sensor_summary", "equipment_signal", "fixed_report"),
    "query_enterprise_data": ("sample", "enterprise_sample", "record", "fixed_report"),
    "search_knowledge": ("document", "knowledge_document", "document", "fixed_report"),
}


def descriptor_for_tool(source_ref: str, tool: str, arguments: dict[str, Any], *, scope_role: str = "primary", expected_scope: EvidenceScope | None = None, semantic_id: str | None = None, grain: str | None = None, kind: str | None = None, provenance: str | None = None) -> EvidenceDescriptor:
    inferred_kind, inferred_semantic_id, inferred_grain, inferred_provenance = _TOOL_SEMANTICS.get(tool, ("unknown", "unknown", "unknown", "unknown"))
    # Query results are only governed when the planner supplied a known template marker.
    if tool == "query_manufacturing_data":
        inferred_provenance = "planner_template" if str(arguments.get("_semantic_template", "")).strip() else "unknown"
        inferred_kind = "metric" if inferred_provenance != "unknown" else "unknown"
        inferred_semantic_id = str(arguments.get("_semantic_id", "unknown"))
        inferred_grain = str(arguments.get("_semantic_grain", "unknown"))
    return EvidenceDescriptor(
        source_ref=source_ref,
        kind=kind or inferred_kind, semantic_id=semantic_id or inferred_semantic_id,
        scope=expected_scope or EvidenceScope.from_arguments(arguments),
        grain=grain or inferred_grain,
        start=str(arguments["start"]) if arguments.get("start") else None,
        end=str(arguments["end"]) if arguments.get("end") else None,
        aggregation="reported",
        filter_provenance=provenance or inferred_provenance,
        scope_role=scope_role,
    )
