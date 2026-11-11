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
        # An unscoped claim neither narrows nor broadens an unscoped observation;
        # a scoped observation still cannot support a broad, unscoped claim.
        return ScopeRelation.EXACT if evidence.is_empty() else ScopeRelation.UNKNOWN
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


def compatible_for_composite_inference(descriptors: list[EvidenceDescriptor]) -> bool:
    """Return whether direct observations can be combined as one inference.

    A composite is an explanation over independently checked observations, not
    a new measurement.  Therefore it may combine different metrics, but every
    input must have known provenance, the same explicit scope and bounded time
    range, and primary (rather than context-only) scope.  Unknown descriptors
    fail closed instead of being silently broadened by the synthesizer.
    """
    if len(descriptors) < 2:
        return False
    first = descriptors[0]
    if (
        first.filter_provenance == "unknown"
        or first.scope.is_empty()
        or first.scope_role == "context_only"
        or bool(first.start) != bool(first.end)
    ):
        return False
    for descriptor in descriptors[1:]:
        if (
            descriptor.filter_provenance == "unknown"
            or descriptor.scope.is_empty()
            or descriptor.scope_role == "context_only"
            or bool(descriptor.start) != bool(descriptor.end)
            or scope_relation(first.scope, descriptor.scope) is not ScopeRelation.EXACT
            or descriptor.start != first.start
            or descriptor.end != first.end
        ):
            return False
    return True


def descriptor_for_tool(source_ref: str, tool: str, arguments: dict[str, Any], *, scope_role: str = "primary", expected_scope: EvidenceScope | None = None, semantic_id: str | None = None, grain: str | None = None, kind: str | None = None, provenance: str | None = None) -> EvidenceDescriptor:
    return EvidenceDescriptor(
        source_ref=source_ref,
        kind=kind or 'unknown', semantic_id=semantic_id or 'unknown',
        scope=expected_scope or EvidenceScope.from_arguments(arguments),
        grain=grain or 'unknown',
        start=str(arguments["start"]) if arguments.get("start") else None,
        end=str(arguments["end"]) if arguments.get("end") else None,
        aggregation="reported",
        filter_provenance=provenance or 'unknown',
        scope_role=scope_role,
    )
