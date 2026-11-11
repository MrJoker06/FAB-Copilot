"""Versioned manufacturing checks used by default diagnostics and the Cpk Skill."""

from __future__ import annotations
import re
import math
from functools import partial
from typing import Any
from ...core.call_scope import call_scope
from ...evidence.contracts import EvidencePolicy
from ...evidence.validator import (
    EvidenceObservation,
    EvidenceValidation,
    ValidationIssue,
    PlanStepView,
    _rows,
    _has_value,
    validate_evidence as evaluate_evidence,
)
from ...tools.evidence_descriptors import descriptor_for_tool

_SCOPE_PARAMETERS = (
    "start",
    "end",
    "process_step",
    "equipment_id",
    "lot_id",
    "source_types",
    "sql",
)
_NAMED_QUERY_TOOLS = frozenset(
    {
        "get_product_yield_breakdown",
        "get_equipment_event_timeline",
        "get_equipment_excursion_history",
        "get_lot_identity",
        "get_lot_process_history",
        "get_lot_excursion_history",
        "get_lot_defect_history",
        "get_lot_wafer_map_patterns",
    }
)
_SAMPLE_FIELDS = (
    "samples",
    "lots",
    "wafers",
    "runs",
    "tested_dies",
    "recorded_minutes",
)
_SPEC_FIELDS = ("spec_lsl", "spec_usl")


def _normalize_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip().upper()
        return re.sub(r"\s+", " ", normalized) if key == "sql" else normalized
    if isinstance(value, list):
        items = tuple(_normalize_value(key, item) for item in value)
        return tuple(sorted(items)) if key == "source_types" else items
    return value


def _declared_scope(step: PlanStepView) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(str(item).upper() for item in values)
        for name, values in (step.evidence_scope or {}).items()
        if values
    }


def _step_matches(step: PlanStepView, observation: EvidenceObservation) -> bool:
    if step.tool != observation.tool:
        return False
    if step.tool in _NAMED_QUERY_TOOLS:
        keys = ("start", "end", "product", "process_step", "equipment_id", "lot_id")
        return all(
            step.parameters.get(key) == observation.arguments.get(key)
            for key in keys
            if key in step.parameters or key in observation.arguments
        )
    declared = _declared_scope(step)
    if declared:
        # The native dispatcher reports the result's own source scope instead of
        # the submitted filters, so compare the declared result scope with the
        # scope implied by the executed arguments rather than raw parameters.
        actual = {
            name: tuple(values)
            for name, values in call_scope(
                step.tool, observation.arguments, step.evidence_ids
            ).items()
            if values
        }
        return declared == actual
    for key in _SCOPE_PARAMETERS:
        if key not in step.parameters:
            continue
        if key not in observation.arguments:
            return False
        if _normalize_value(key, step.parameters[key]) != _normalize_value(
            key, observation.arguments[key]
        ):
            return False
    return True


def _sample_and_source_risks(
    matched: list[tuple[EvidenceObservation, set[str]]],
    *,
    sample_fields: tuple[str, ...] = _SAMPLE_FIELDS,
    minimum_sample_count: int = 30,
) -> list[ValidationIssue]:
    risks: list[ValidationIssue] = []
    for observation, evidence_ids in matched:
        rows = _rows(observation.result)
        ids = tuple(sorted(evidence_ids))
        if not rows:
            risks.append(
                ValidationIssue(
                    code="empty_result",
                    severity="critical",
                    evidence_ids=ids,
                    message=f"{observation.tool} 返回空结果。",
                    source_ref=f"TOOL:{observation.tool}",
                )
            )
            continue

        for field in sample_fields:
            values = [
                float(row[field])
                for row in rows
                if _has_value(row, field) and isinstance(row[field], (int, float))
            ]
            positive = [value for value in values if value > 0]
            if positive and min(positive) < minimum_sample_count:
                risks.append(
                    ValidationIssue(
                        code="small_sample",
                        severity="warning",
                        evidence_ids=ids,
                        message=f"{observation.tool} 的 {field} 最小样本为 {min(positive):g}，低于 {minimum_sample_count}，仅适合形成有限结论。",
                        source_ref=f"TOOL:{observation.tool}",
                    )
                )

        limit = observation.arguments.get("limit")
        if (
            isinstance(observation.result, list)
            and isinstance(limit, int)
            and len(observation.result) >= limit
        ):
            risks.append(
                ValidationIssue(
                    code="result_truncated",
                    severity="warning",
                    evidence_ids=ids,
                    message=f"{observation.tool} 返回 {len(observation.result)} 行并达到 limit={limit}，频次或分布可能受截断影响。",
                    source_ref=f"TOOL:{observation.tool}",
                )
            )

        confidences = [
            str(row.get("retrieval", {}).get("confidence", "")).lower()
            for row in rows
            if isinstance(row.get("retrieval"), dict)
        ]
        if confidences and all(value == "low" for value in confidences):
            risks.append(
                ValidationIssue(
                    code="low_source_confidence",
                    severity="critical",
                    evidence_ids=ids,
                    message=f"{observation.tool} 的检索结果全部为低置信度，不能支持确定性结论。",
                    source_ref=f"TOOL:{observation.tool}",
                )
            )
        elif "low" in confidences:
            risks.append(
                ValidationIssue(
                    code="mixed_source_confidence",
                    severity="warning",
                    evidence_ids=ids,
                    message=f"{observation.tool} 包含低置信度来源，引用时必须逐项区分。",
                    source_ref=f"TOOL:{observation.tool}",
                )
            )
    return risks


def _fact_conflicts(
    matched: list[tuple[EvidenceObservation, set[str]]],
) -> list[ValidationIssue]:
    values: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    evidence: dict[tuple[str, str, str], set[str]] = {}
    for observation, evidence_ids in matched:
        for row in _rows(observation.result):
            metric = str(row.get("metric_name") or row.get("measurement_name") or "")
            equipment = str(row.get("equipment_id") or "")
            if equipment and metric:
                identity = f"{equipment}|{metric}"
                for field in _SPEC_FIELDS:
                    if _has_value(row, field):
                        key = ("specification", identity, field)
                        values.setdefault(key, {}).setdefault(
                            str(row[field]), set()
                        ).add(observation.tool)
                        evidence.setdefault(key, set()).update(evidence_ids)

            reference_id = str(row.get("reference_id") or "")
            if reference_id:
                for field in ("status", "version", "effective_date"):
                    if _has_value(row, field):
                        key = ("document", reference_id, field)
                        values.setdefault(key, {}).setdefault(
                            str(row[field]), set()
                        ).add(observation.tool)
                        evidence.setdefault(key, set()).update(evidence_ids)

    conflicts: list[ValidationIssue] = []
    for (kind, identity, field), variants in values.items():
        if len(variants) < 2:
            continue
        displayed = ", ".join(sorted(variants))
        conflicts.append(
            ValidationIssue(
                code="fact_conflict",
                severity="critical",
                evidence_ids=tuple(sorted(evidence[(kind, identity, field)])),
                message=f"{kind} {identity} 的 {field} 存在冲突值：{displayed}。",
            )
        )
    return conflicts


def _same(value: object, expected: object) -> bool:
    if isinstance(value, list):
        return (
            tuple(value) == tuple(expected)
            if isinstance(expected, (list, tuple))
            else False
        )
    return value == expected


def skill_step_matcher(step: object, observation: EvidenceObservation) -> bool:
    """Require native retrieval focus only for the controlled knowledge step."""
    if getattr(step, "tool", None) != "search_knowledge":
        return _step_matches(step, observation)
    parameters = getattr(step, "parameters", {})
    if observation.tool != "search_knowledge" or not isinstance(parameters, dict):
        return False
    for name in ("query", "source_types", "limit"):
        if not _same(observation.arguments.get(name), parameters.get(name)):
            return False
    expected_process = parameters.get("process_step")
    expected_equipment = parameters.get("equipment_id")
    for name, expected in (
        ("process_step", expected_process),
        ("equipment_id", expected_equipment),
    ):
        if name in observation.arguments and observation.arguments[name] != expected:
            return False
    rows = observation.result if isinstance(observation.result, list) else []
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        filters = (
            row.get("retrieval", {}).get("filters", {})
            if isinstance(row.get("retrieval"), dict)
            else {}
        )
        if not isinstance(filters, dict):
            return False
        if (
            expected_process is not None
            and filters.get("process_step") != expected_process
        ):
            return False
        if (
            expected_equipment is not None
            and filters.get("equipment_id") != expected_equipment
        ):
            return False
    return True


def _sample_and_source_risks_v2(matched, *, sample_fields, minimum_sample_count):
    risks = _sample_and_source_risks(
        matched, sample_fields=sample_fields, minimum_sample_count=minimum_sample_count
    )
    for observation, evidence_ids in matched:
        for row in _rows(observation.result):
            for name in sample_fields:
                if name not in row:
                    continue
                value = row[name]
                if (
                    type(value) not in {int, float}
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    risks.append(
                        ValidationIssue(
                            "invalid_sample",
                            "critical",
                            tuple(sorted(evidence_ids)),
                            f"{observation.tool} 的 {name} 不能证明存在有效样本。",
                            source_ref=f"TOOL:{observation.tool}",
                        )
                    )
            if row.get("source_type") == "knowledge":
                risks.append(
                    ValidationIssue(
                        "document_status_unverified",
                        "warning",
                        tuple(sorted(evidence_ids)),
                        "知识条目的批准状态与生效性尚未核实，不能仅凭来源类型视作生效 SOP。",
                        source_ref=f"TOOL:{observation.tool}",
                    )
                )
    return risks


def _separate_effective_windows(first, second):
    """Only explicit, well-formed disjoint windows justify separate specs."""
    from datetime import date

    windows = []
    for row in (first, second):
        start, end = row.get("effective_from"), row.get("effective_to")
        if not isinstance(start, str) or not isinstance(end, str):
            return False
        try:
            interval = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            return False
        if interval[0] > interval[1]:
            return False
        windows.append(interval)
    return windows[0][1] < windows[1][0] or windows[1][1] < windows[0][0]


def _fact_conflicts_v2(matched):
    # Keep document checks, but compare measurement specs using their actual
    # available comparability metadata. Never change the observations in place.
    documents = {}
    groups = {}
    for observation, ids in matched:
        rows = _rows(observation.result)
        for row in rows:
            if row.get("reference_id"):
                documents.setdefault(str(row["reference_id"]), []).append((row, ids))
            metric = row.get("metric_name") or row.get("measurement_name")
            if not row.get("equipment_id") or not metric:
                continue
            key = str(row["equipment_id"]), str(metric)
            groups.setdefault(key, []).append((row, ids))
    conflicts = []
    for reference, rows in documents.items():
        for index, (first, first_ids) in enumerate(rows):
            for second, second_ids in rows[index + 1 :]:
                differences = [
                    name
                    for name in ("status", "version", "effective_date")
                    if _has_value(first, name)
                    and _has_value(second, name)
                    and first[name] != second[name]
                ]
                if not differences or _separate_effective_windows(first, second):
                    continue
                conflicts.append(
                    ValidationIssue(
                        "comparability_unconfirmed"
                        if "version" in differences
                        else "fact_conflict",
                        "critical",
                        tuple(sorted(set(first_ids) | set(second_ids))),
                        f"document {reference} 的版本、状态或生效口径尚未统一。",
                    )
                )
    for identity, rows in groups.items():
        for index, (first, first_ids) in enumerate(rows):
            for second, second_ids in rows[index + 1 :]:
                differing = [
                    name
                    for name in _SPEC_FIELDS
                    if _has_value(first, name)
                    and _has_value(second, name)
                    and first[name] != second[name]
                ]
                if _separate_effective_windows(first, second):
                    continue
                first_unit = first.get("metric_unit") or first.get("measurement_unit")
                second_unit = second.get("metric_unit") or second.get(
                    "measurement_unit"
                )
                first_version, second_version = (
                    first.get("spec_version"),
                    second.get("spec_version"),
                )
                incomparable = (
                    first_unit and second_unit and first_unit != second_unit
                ) or (
                    first_version and second_version and first_version != second_version
                )
                if not differing and not incomparable:
                    continue
                conflicts.append(
                    ValidationIssue(
                        "comparability_unconfirmed"
                        if incomparable
                        else "fact_conflict",
                        "critical",
                        tuple(sorted(set(first_ids) | set(second_ids))),
                        f"specification {'|'.join(identity)} 的规格限不一致，"
                        + (
                            "单位、版本或生效窗不足以证明口径可比较。"
                            if incomparable
                            else "尚未证明存在独立生效区间。"
                        ),
                    )
                )
    return conflicts


def policy_for(
    playbook: object, *, skill: bool = False, version: str | None = None
) -> EvidencePolicy:
    version = version or ("1.3.0" if skill else "1.2.0")
    if version not in ({"1.3.0", "2.0.0"} if skill else {"1.2.0", "2.0.0"}):
        raise ValueError("unsupported evidence policy version")
    return EvidencePolicy(
        component_id="capability-evidence" if skill else playbook.playbook_id,
        version=version,
        evidence_requirements=tuple(playbook.evidence_requirements),
        step_matcher=skill_step_matcher
        if skill or version == "2.0.0"
        else _step_matches,
        risk_checker=partial(
            _sample_and_source_risks_v2,
            sample_fields=_SAMPLE_FIELDS,
            minimum_sample_count=30,
        )
        if version == "2.0.0"
        else _sample_and_source_risks,
        conflict_checker=_fact_conflicts_v2 if version == "2.0.0" else _fact_conflicts,
        describe_source=descriptor_for_tool,
        row_modes=(("CAP-01", "each_row"), ("CAP-02", "each_row"))
        if version == "2.0.0"
        else (),
    )


def validate_skill_evidence(
    plan: object, playbook: object, observations: list[EvidenceObservation]
) -> EvidenceValidation:
    return evaluate_evidence(plan, policy_for(playbook, skill=True), observations)


def validate_skill_evidence_v2(
    plan: object, playbook: object, observations: list[EvidenceObservation]
) -> EvidenceValidation:
    return evaluate_evidence(
        plan, policy_for(playbook, skill=True, version="2.0.0"), observations
    )
