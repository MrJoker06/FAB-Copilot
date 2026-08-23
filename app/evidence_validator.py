from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .domain_playbooks import DomainPlaybook
from .planner import ExecutionPlan, PlanStep
from .evidence_semantics import EvidenceScope, descriptor_for_tool


ObservationStatus = Literal["success", "error", "blocked"]
EvidenceStatus = Literal["covered", "partial", "missing", "optional_missing"]
ConclusionStrength = Literal[
    "not_applicable",
    "insufficient",
    "hypothesis_only",
    "supported_with_limits",
    "supported",
]

_SCOPE_PARAMETERS = (
    "start",
    "end",
    "process_step",
    "equipment_id",
    "lot_id",
    "source_types",
    "sql",
)
_SAMPLE_FIELDS = ("samples", "lots", "wafers", "runs", "tested_dies", "recorded_minutes")
_SPEC_FIELDS = ("spec_lsl", "spec_usl")


@dataclass(frozen=True)
class EvidenceObservation:
    tool: str
    arguments: dict[str, Any]
    status: ObservationStatus
    result: Any = None
    error: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class EvidenceCheck:
    evidence_id: str
    name: str
    required: bool
    status: EvidenceStatus
    matched_tools: tuple[str, ...]
    successful_calls: int
    row_count: int
    present_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Literal["info", "warning", "critical"]
    evidence_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class EvidenceValidation:
    schema_version: str
    validator_version: str
    plan_id: str
    status: Literal["validated", "not_applicable"]
    coverage: dict[str, int | float]
    evidence_checks: tuple[EvidenceCheck, ...]
    risks: tuple[ValidationIssue, ...]
    conflicts: tuple[ValidationIssue, ...]
    primary_scope_type: str
    primary_scope_ids: tuple[str, ...]
    primary_scope_labels: tuple[str, ...]
    source_scope_roles: dict[str, str]
    source_semantics: dict[str, dict[str, Any]]
    observed_source_refs: tuple[str, ...]
    allowed_conclusion_strength: ConclusionStrength
    conclusion_guidance: str
    causal_claims_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, default=str))

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _normalize_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip().upper()
        return re.sub(r"\s+", " ", normalized) if key == "sql" else normalized
    if isinstance(value, list):
        items = tuple(_normalize_value(key, item) for item in value)
        return tuple(sorted(items)) if key == "source_types" else items
    return value


def _source_scope_roles(plan: ExecutionPlan) -> dict[str, str]:
    roles: dict[str, str] = {}
    for step in plan.steps:
        roles[f"TOOL:{step.step_id}"] = step.scope_role
        reference = f"TOOL:{step.tool}"
        if reference not in roles:
            roles[reference] = step.scope_role
        elif roles[reference] != step.scope_role:
            roles[reference] = "unknown"
    return roles


def _source_semantics(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for step in plan.steps:
        descriptor = descriptor_for_tool(
            f"TOOL:{step.step_id}", step.tool, step.parameters, scope_role=step.scope_role,
            expected_scope=EvidenceScope(**(step.evidence_scope or {})), semantic_id=step.semantic_id,
            grain=step.grain, kind=step.evidence_kind, provenance=step.filter_provenance,
        )
        result[descriptor.source_ref] = {
            "kind": descriptor.kind, "semantic_id": step.semantic_id, "grain": step.grain,
            "scope": descriptor.scope.__dict__, "start": step.evidence_start, "end": step.evidence_end,
            "filter_provenance": descriptor.filter_provenance, "scope_role": descriptor.scope_role,
        }
    return result


def _step_matches(step: PlanStep, observation: EvidenceObservation) -> bool:
    if step.tool != observation.tool:
        return False
    for key in _SCOPE_PARAMETERS:
        if key not in step.parameters:
            continue
        if key not in observation.arguments:
            return False
        if _normalize_value(key, step.parameters[key]) != _normalize_value(key, observation.arguments[key]):
            return False
    return True


def _matching_evidence_ids(plan: ExecutionPlan, observation: EvidenceObservation) -> set[str]:
    return {
        evidence_id
        for step in plan.steps
        if _step_matches(step, observation)
        for evidence_id in step.evidence_ids
    }


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _has_value(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    return value is not None and value != "" and value != []


def _deduplicate_issues(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    unique: dict[tuple[str, tuple[str, ...], str], ValidationIssue] = {}
    for issue in issues:
        unique[(issue.code, issue.evidence_ids, issue.message)] = issue
    return tuple(unique.values())


def _scope_risks(
    plan: ExecutionPlan,
    playbook: DomainPlaybook,
    observations: list[EvidenceObservation],
) -> list[ValidationIssue]:
    risks: list[ValidationIssue] = []
    for observation in observations:
        if observation.status != "success":
            continue
        source_ids = tuple(
            item.evidence_id
            for item in playbook.evidence_requirements
            if observation.tool in item.source_tools
        )
        if not source_ids or _matching_evidence_ids(plan, observation):
            continue
        risks.append(ValidationIssue(
            code="scope_mismatch",
            severity="critical",
            evidence_ids=source_ids,
            message=f"{observation.tool} 的实际参数与计划时间或分析范围不一致，结果未计入证据。",
        ))
    return risks


def _sample_and_source_risks(
    matched: list[tuple[EvidenceObservation, set[str]]],
) -> list[ValidationIssue]:
    risks: list[ValidationIssue] = []
    for observation, evidence_ids in matched:
        rows = _rows(observation.result)
        ids = tuple(sorted(evidence_ids))
        if not rows:
            risks.append(ValidationIssue(
                code="empty_result",
                severity="critical",
                evidence_ids=ids,
                message=f"{observation.tool} 返回空结果。",
            ))
            continue

        for field in _SAMPLE_FIELDS:
            values = [float(row[field]) for row in rows if _has_value(row, field) and isinstance(row[field], (int, float))]
            positive = [value for value in values if value > 0]
            if positive and min(positive) < 30:
                risks.append(ValidationIssue(
                    code="small_sample",
                    severity="warning",
                    evidence_ids=ids,
                    message=f"{observation.tool} 的 {field} 最小样本为 {min(positive):g}，低于 30，仅适合形成有限结论。",
                ))

        limit = observation.arguments.get("limit")
        if isinstance(observation.result, list) and isinstance(limit, int) and len(observation.result) >= limit:
            risks.append(ValidationIssue(
                code="result_truncated",
                severity="warning",
                evidence_ids=ids,
                message=f"{observation.tool} 返回 {len(observation.result)} 行并达到 limit={limit}，频次或分布可能受截断影响。",
            ))

        confidences = [
            str(row.get("retrieval", {}).get("confidence", "")).lower()
            for row in rows
            if isinstance(row.get("retrieval"), dict)
        ]
        if confidences and all(value == "low" for value in confidences):
            risks.append(ValidationIssue(
                code="low_source_confidence",
                severity="critical",
                evidence_ids=ids,
                message=f"{observation.tool} 的检索结果全部为低置信度，不能支持确定性结论。",
            ))
        elif "low" in confidences:
            risks.append(ValidationIssue(
                code="mixed_source_confidence",
                severity="warning",
                evidence_ids=ids,
                message=f"{observation.tool} 包含低置信度来源，引用时必须逐项区分。",
            ))
    return risks


def _execution_risks(
    plan: ExecutionPlan,
    playbook: DomainPlaybook,
    observations: list[EvidenceObservation],
) -> list[ValidationIssue]:
    risks: list[ValidationIssue] = []
    for observation in observations:
        if observation.status == "success":
            continue
        evidence_ids = {
            evidence_id
            for step in plan.steps
            if step.tool == observation.tool
            for evidence_id in step.evidence_ids
        }
        if not evidence_ids:
            evidence_ids = {
                requirement.evidence_id
                for requirement in playbook.evidence_requirements
                if observation.tool in requirement.source_tools
            }
        if evidence_ids:
            risks.append(ValidationIssue(
                code="tool_not_completed",
                severity="warning",
                evidence_ids=tuple(sorted(evidence_ids)),
                message=f"{observation.tool} 调用状态为 {observation.status}，未产生可验证证据。",
            ))
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
                        values.setdefault(key, {}).setdefault(str(row[field]), set()).add(observation.tool)
                        evidence.setdefault(key, set()).update(evidence_ids)

            reference_id = str(row.get("reference_id") or "")
            if reference_id:
                for field in ("status", "version", "effective_date"):
                    if _has_value(row, field):
                        key = ("document", reference_id, field)
                        values.setdefault(key, {}).setdefault(str(row[field]), set()).add(observation.tool)
                        evidence.setdefault(key, set()).update(evidence_ids)

    conflicts: list[ValidationIssue] = []
    for (kind, identity, field), variants in values.items():
        if len(variants) < 2:
            continue
        displayed = ", ".join(sorted(variants))
        conflicts.append(ValidationIssue(
            code="fact_conflict",
            severity="critical",
            evidence_ids=tuple(sorted(evidence[(kind, identity, field)])),
            message=f"{kind} {identity} 的 {field} 存在冲突值：{displayed}。",
        ))
    return conflicts


def _strength(
    required_total: int,
    required_covered: int,
    risks: tuple[ValidationIssue, ...],
    conflicts: tuple[ValidationIssue, ...],
) -> ConclusionStrength:
    if required_total == 0:
        return "not_applicable"
    if required_covered == 0:
        return "insufficient"
    critical = any(item.severity == "critical" for item in (*risks, *conflicts))
    if required_covered < required_total or critical:
        return "hypothesis_only"
    if risks or conflicts:
        return "supported_with_limits"
    return "supported"


_GUIDANCE: dict[ConclusionStrength, str] = {
    "not_applicable": "当前没有适用的领域证据契约；按通用规则回答并明确数据来源。",
    "insufficient": "必需证据不足，不得给出诊断性或因果性结论；只能说明已知事实、证据缺口和补充查询要求。",
    "hypothesis_only": "只能给出待验证假设并逐项说明依据与反证方法；不得使用‘主要原因’、‘已经导致’等确定性措辞。",
    "supported_with_limits": "可以给出受证据支持的方向性结论，但必须同时披露样本、截断、来源或口径限制。",
    "supported": "可以给出当前证据直接支持的结论；相关性仍不得表述为已证明的因果关系。",
}


def validate_evidence(
    plan: ExecutionPlan,
    playbook: DomainPlaybook | None,
    observations: list[EvidenceObservation],
) -> EvidenceValidation:
    if plan.status != "ready" or playbook is None:
        strength: ConclusionStrength = "not_applicable"
        return EvidenceValidation(
            schema_version="1.1",
            validator_version="1.1.0",
            plan_id=plan.plan_id,
            status="not_applicable",
            coverage={
                "required_total": 0,
                "required_covered": 0,
                "required_coverage_pct": 0.0,
                "field_coverage_pct": 0.0,
            },
            evidence_checks=(),
            risks=(),
            conflicts=(),
            primary_scope_type=plan.scope_contract.primary_scope_type,
            primary_scope_ids=plan.scope_contract.primary_scope_ids,
            primary_scope_labels=plan.scope_contract.primary_scope_labels,
            source_scope_roles=_source_scope_roles(plan),
            source_semantics=_source_semantics(plan),
            observed_source_refs=(),
            allowed_conclusion_strength=strength,
            conclusion_guidance=_GUIDANCE[strength],
        )

    matched = [
        (observation, _matching_evidence_ids(plan, observation))
        for observation in observations
        if observation.status == "success"
    ]
    matched = [(observation, ids) for observation, ids in matched if ids]
    checks: list[EvidenceCheck] = []
    total_fields = 0
    present_fields_count = 0
    for requirement in playbook.evidence_requirements:
        effective_required = requirement.required or any(
            step.required and requirement.evidence_id in step.evidence_ids for step in plan.steps
        )
        related = [observation for observation, ids in matched if requirement.evidence_id in ids]
        successful = [observation for observation in related if _rows(observation.result)]
        rows = [row for observation in successful for row in _rows(observation.result)]
        present = tuple(field for field in requirement.required_fields if any(_has_value(row, field) for row in rows))
        missing = tuple(field for field in requirement.required_fields if field not in present)
        if effective_required:
            total_fields += len(requirement.required_fields)
            present_fields_count += len(present)
        if successful and not missing:
            status: EvidenceStatus = "covered"
        elif related:
            status = "partial"
        else:
            status = "missing" if effective_required else "optional_missing"
        checks.append(EvidenceCheck(
            evidence_id=requirement.evidence_id,
            name=requirement.name,
            required=effective_required,
            status=status,
            matched_tools=tuple(dict.fromkeys(item.tool for item in related)),
            successful_calls=len(successful),
            row_count=sum(len(_rows(item.result)) for item in successful),
            present_fields=present,
            missing_fields=missing,
        ))

    required_checks = [item for item in checks if item.required]
    required_covered = sum(item.status == "covered" for item in required_checks)
    risks = _deduplicate_issues(
        _scope_risks(plan, playbook, observations)
        + _execution_risks(plan, playbook, observations)
        + _sample_and_source_risks(matched)
    )
    conflicts = _deduplicate_issues(_fact_conflicts(matched))
    strength = _strength(len(required_checks), required_covered, risks, conflicts)
    observed_refs = {
        f"TOOL:{observation.tool}"
        for observation, _ in matched
    }
    for observation, _ in matched:
        observed_refs.add(observation.source_ref or "")
        observed_refs.update(f"TOOL:{step.step_id}" for step in plan.steps if _step_matches(step, observation))
    observed_refs.discard("")
    return EvidenceValidation(
        schema_version="1.1",
        validator_version="1.1.0",
        plan_id=plan.plan_id,
        status="validated",
        coverage={
            "required_total": len(required_checks),
            "required_covered": required_covered,
            "required_coverage_pct": round(100.0 * required_covered / max(1, len(required_checks)), 1),
            "field_coverage_pct": round(100.0 * present_fields_count / max(1, total_fields), 1),
        },
        evidence_checks=tuple(checks),
        risks=risks,
        conflicts=conflicts,
        primary_scope_type=plan.scope_contract.primary_scope_type,
        primary_scope_ids=plan.scope_contract.primary_scope_ids,
        primary_scope_labels=plan.scope_contract.primary_scope_labels,
        source_scope_roles=_source_scope_roles(plan),
        source_semantics=_source_semantics(plan),
        observed_source_refs=tuple(sorted(observed_refs)),
        allowed_conclusion_strength=strength,
        conclusion_guidance=_GUIDANCE[strength],
    )


def validator_system_message(validation: EvidenceValidation) -> str:
    return (
        "以下 evidence_validation 是基于实际工具结果生成的确定性约束，不是制造事实本身。"
        "若上下文中存在多份报告，以最后一份为准。"
        "最终回答不得超过 allowed_conclusion_strength；必须披露 missing/partial 证据、critical 风险和冲突。"
        "source_scope_roles=context_only 的工具只能提供背景，不能支持 primary_scope 的专属指标或结论。"
        "causal_claims_allowed=false 时不得把相关性表述为已证明因果。\n"
        f"evidence_validation={validation.to_prompt()}"
    )
