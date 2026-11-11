from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from .contracts import EvidencePolicy
from .semantics import EvidenceScope, descriptor_for_tool
from .serialization import json_dataclass_payload

ObservationStatus = Literal["success", "error", "blocked"]
EvidenceStatus = Literal["covered", "partial", "missing", "optional_missing"]
ConclusionStrength = Literal[
    "not_applicable",
    "insufficient",
    "hypothesis_only",
    "supported_with_limits",
    "supported",
]

# Evidence-owned read-only views of the plan and playbook facts the validator
# consumes.  ``planning_runtime.contracts.ExecutionPlan``/``PlanStep`` and
# `EvidencePolicy`/`EvidenceRequirement` satisfy
# them structurally, so evidence does not import orchestration modules.
class PlanStepView(Protocol):
    @property
    def step_id(self) -> str: ...

    @property
    def tool(self) -> str: ...

    @property
    def parameters(self) -> Mapping[str, Any]: ...

    @property
    def evidence_ids(self) -> tuple[str, ...]: ...

    @property
    def required(self) -> bool: ...

    @property
    def scope_role(self) -> str: ...

    @property
    def semantic_id(self) -> str: ...

    @property
    def grain(self) -> str: ...

    @property
    def filter_provenance(self) -> str: ...

    @property
    def evidence_kind(self) -> str: ...

    @property
    def evidence_scope(self) -> Mapping[str, tuple[str, ...]] | None: ...

    @property
    def evidence_start(self) -> str | None: ...

    @property
    def evidence_end(self) -> str | None: ...


class PlanScopeView(Protocol):
    @property
    def primary_scope_type(self) -> str: ...

    @property
    def primary_scope_ids(self) -> tuple[str, ...]: ...

    @property
    def primary_scope_labels(self) -> tuple[str, ...]: ...


class ExecutionPlanView(Protocol):
    @property
    def plan_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def scope_contract(self) -> PlanScopeView: ...

    @property
    def steps(self) -> tuple[PlanStepView, ...]: ...


class EvidenceRequirementView(Protocol):
    @property
    def evidence_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def source_tools(self) -> tuple[str, ...]: ...

    @property
    def required_fields(self) -> tuple[str, ...]: ...

    @property
    def required(self) -> bool: ...


class EvidencePolicyView(Protocol):
    @property
    def evidence_requirements(self) -> tuple[EvidenceRequirementView, ...]: ...


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
    # Call-level attribution.  ``None`` keeps requirement-level semantics for
    # risks that genuinely span several calls (for example a fact conflict).
    source_ref: str | None = None


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
    # Per-reference evidence state is additive so previously persisted validation
    # payloads remain readable.  It lets synthesis assess a claim independently
    # of the task-wide conclusion strength.
    reference_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    assessment_status: str | None = None
    assessment_reason: str | None = None
    policy_ref: dict[str, str] | None = None
    evidence_sufficient: bool | None = None

    @property
    def enforced(self) -> bool:
        """An unavailable required check must not enable ungoverned answers."""
        return (
            self.policy_ref is not None and self.assessment_reason != "plan_not_ready"
        ) or self.status == "validated"

    def to_dict(self) -> dict[str, Any]:
        return json_dataclass_payload(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))




def _source_scope_roles(plan: ExecutionPlanView) -> dict[str, str]:
    roles: dict[str, str] = {}
    for step in plan.steps:
        roles[f"TOOL:{step.step_id}"] = step.scope_role
        reference = f"TOOL:{step.tool}"
        if reference not in roles:
            roles[reference] = step.scope_role
        elif roles[reference] != step.scope_role:
            roles[reference] = "unknown"
    return roles


def _source_semantics(plan: ExecutionPlanView, describe_source: Callable = descriptor_for_tool) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for step in plan.steps:
        descriptor = describe_source(
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






def _matching_evidence_ids(plan: ExecutionPlanView, observation: EvidenceObservation, step_matcher: Callable[[PlanStepView, EvidenceObservation], bool] | None = None) -> set[str]:
    matcher = step_matcher
    return {
        evidence_id
        for step in plan.steps
        if matcher(step, observation)
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
    unique: dict[tuple[str, tuple[str, ...], str, str | None], ValidationIssue] = {}
    for issue in issues:
        unique[(issue.code, issue.evidence_ids, issue.message, issue.source_ref)] = issue
    return tuple(unique.values())


def _scope_risks(
    plan: ExecutionPlanView,
    playbook: EvidencePolicyView,
    observations: list[EvidenceObservation],
    step_matcher: Callable[[PlanStepView, EvidenceObservation], bool] | None = None,
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
        if not source_ids or _matching_evidence_ids(plan, observation, step_matcher):
            continue
        risks.append(ValidationIssue(
            code="scope_mismatch",
            severity="critical",
            evidence_ids=source_ids,
            message=f"{observation.tool} 的实际参数与计划时间或分析范围不一致，结果未计入证据。",
            source_ref=f"TOOL:{observation.tool}",
        ))
    return risks




def _execution_risks(
    plan: ExecutionPlanView,
    playbook: EvidencePolicyView,
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
                source_ref=f"TOOL:{observation.tool}",
            ))
    return risks




def _reference_evidence(
    plan: ExecutionPlanView,
    matched: list[tuple[EvidenceObservation, set[str]]],
    checks: list[EvidenceCheck],
    risks: tuple[ValidationIssue, ...],
    conflicts: tuple[ValidationIssue, ...],
    step_matcher: Callable[[PlanStepView, EvidenceObservation], bool] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map each observed call reference to its concrete evidence obligations."""
    status_by_id = {item.evidence_id: item.status for item in checks}
    refs: dict[str, set[str]] = {}
    call_refs: dict[str, set[str]] = {}
    for observation, evidence_ids in matched:
        targets = {f"TOOL:{observation.tool}"}
        targets.update(
            f"TOOL:{step.step_id}" for step in plan.steps if step_matcher(step, observation)
        )
        if observation.source_ref:
            targets.add(observation.source_ref)
        for reference in targets:
            refs.setdefault(reference, set()).update(evidence_ids)
            call_refs.setdefault(reference, set()).update(targets)

    def applies(issue: ValidationIssue, reference: str, evidence_ids: set[str]) -> bool:
        if issue.source_ref:
            return issue.source_ref in call_refs.get(reference, ()) or issue.source_ref == reference
        return bool(set(issue.evidence_ids).intersection(evidence_ids))

    result: dict[str, dict[str, Any]] = {}
    for reference, evidence_ids in refs.items():
        ids = tuple(sorted(evidence_ids))
        related_risks = tuple(
            item.code for item in risks if applies(item, reference, evidence_ids)
        )
        related_conflicts = tuple(
            item.code for item in conflicts if set(item.evidence_ids).intersection(evidence_ids)
        )
        result[reference] = {
            "evidence_ids": ids,
            "statuses": {item: status_by_id.get(item, "missing") for item in ids},
            "risk_codes": related_risks,
            "conflict_codes": related_conflicts,
            "critical_risk_codes": tuple(
                item.code for item in risks
                if item.severity == "critical" and applies(item, reference, evidence_ids)
            ),
        }
    return result


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
    "hypothesis_only": "任务级诊断或根因只能作为待验证假设并说明依据与反证方法；经逐声明验证的直接观测可以保留，但不得使用‘主要原因’、‘已经导致’等确定性或因果措辞。",
    "supported_with_limits": "可以给出受证据支持的方向性结论，但必须同时披露样本、截断、来源或口径限制。",
    "supported": "可以给出当前证据直接支持的结论；相关性仍不得表述为已证明的因果关系。",
}


def validate_evidence(
    plan: ExecutionPlanView,
    playbook: EvidencePolicy | None,
    observations: list[EvidenceObservation],
    *,
    step_matcher: Callable[[PlanStepView, EvidenceObservation], bool] | None = None,
) -> EvidenceValidation:
    step_matcher = step_matcher or (playbook.step_matcher if playbook is not None else None)
    if plan.status != "ready" or playbook is None:
        strength: ConclusionStrength = "not_applicable"
        return EvidenceValidation(
            schema_version="1.2",
            validator_version=playbook.version if playbook is not None else "1.2.0",
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
            source_semantics=_source_semantics(plan, playbook.describe_source) if playbook is not None else _source_semantics(plan),
            observed_source_refs=(),
            allowed_conclusion_strength=strength,
            conclusion_guidance=_GUIDANCE[strength],
        )

    matched = [
        (observation, _matching_evidence_ids(plan, observation, step_matcher))
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
        mode = dict(playbook.row_modes).get(requirement.evidence_id, "dataset_presence")
        present = tuple(
            field for field in requirement.required_fields
            if rows and (all if mode == "each_row" else any)(
                _has_value(row, field) for row in rows
            )
        )
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
        _scope_risks(plan, playbook, observations, step_matcher)
        + _execution_risks(plan, playbook, observations)
        + playbook.risk_checker(matched)
    )
    conflicts = _deduplicate_issues(playbook.conflict_checker(matched))
    strength = _strength(len(required_checks), required_covered, risks, conflicts)
    observed_refs = {
        f"TOOL:{observation.tool}"
        for observation, _ in matched
    }
    for observation, _ in matched:
        observed_refs.add(observation.source_ref or "")
        observed_refs.update(f"TOOL:{step.step_id}" for step in plan.steps if step_matcher(step, observation))
    observed_refs.discard("")
    reference_evidence = _reference_evidence(plan, matched, checks, risks, conflicts, step_matcher)
    return EvidenceValidation(
        schema_version="1.2",
        validator_version=playbook.version,
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
        source_semantics=_source_semantics(plan, playbook.describe_source) if playbook is not None else _source_semantics(plan),
        observed_source_refs=tuple(sorted(observed_refs)),
        allowed_conclusion_strength=strength,
        conclusion_guidance=_GUIDANCE[strength],
        reference_evidence=reference_evidence,
    )


def validator_system_message(validation: EvidenceValidation) -> str:
    return (
        "以下 evidence_validation 是基于实际工具结果生成的确定性约束，不是制造事实本身。"
        "若上下文中存在多份报告，以最后一份为准。"
        "allowed_conclusion_strength 限制任务级诊断和根因；经逐声明验证的直接观测可保留。"
        "必须披露 missing/partial 证据、critical 风险和冲突。"
        "source_scope_roles=context_only 的工具只能提供背景，不能支持 primary_scope 的专属指标或结论。"
        "causal_claims_allowed=false 时不得把相关性表述为已证明因果。\n"
        f"evidence_validation={validation.to_prompt()}"
    )


def assess_validation(
    plan: ExecutionPlanView,
    policy: EvidencePolicy | None,
    observations: list[EvidenceObservation],
    *,
    evaluate: Callable[[], EvidenceValidation] | None = None,
) -> EvidenceValidation:
    """Validate one trusted checker result, failing closed without doing I/O.

    CancelledError and other BaseExceptions deliberately propagate. The legacy
    report remains the serialized view; there is only one checker invocation.
    """
    reference = (
        {"component_id": policy.component_id, "version": policy.version}
        if policy is not None else None
    )
    if policy is None:
        return replace(
            validate_evidence(plan, None, []),
            assessment_status="not_configured",
            assessment_reason="no_policy",
        )
    reason = "checker_unavailable"
    try:
        report = evaluate() if evaluate is not None else validate_evidence(plan, policy, observations)
        reason = "invalid_checker_result"
        if not isinstance(report, EvidenceValidation):
            closer = getattr(report, "close", None)
            if callable(closer):
                closer()
            raise ValueError
        if (
            report.schema_version != "1.2"
            or report.validator_version != policy.version
            or report.plan_id != plan.plan_id
            or report.status not in {"validated", "not_applicable"}
            or report.allowed_conclusion_strength not in _GUIDANCE
            or report.causal_claims_allowed is not False
        ):
            raise ValueError
        total = report.coverage["required_total"]
        covered = report.coverage["required_covered"]
        if type(total) is not int or type(covered) is not int or not 0 <= covered <= total:
            raise ValueError
        for name in ("required_coverage_pct", "field_coverage_pct"):
            value = report.coverage[name]
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError
        if not isinstance(report.evidence_checks, tuple) or not all(
            isinstance(check, EvidenceCheck)
            and check.status in {"covered", "partial", "missing", "optional_missing"}
            and type(check.required) is bool
            and type(check.row_count) is int and check.row_count >= 0
            for check in report.evidence_checks
        ):
            raise ValueError
        required = [check for check in report.evidence_checks if check.required]
        if len(required) != total or sum(check.status == "covered" for check in required) != covered:
            raise ValueError
        for issue in (*report.risks, *report.conflicts):
            if not isinstance(issue, ValidationIssue) or issue.severity not in {"info", "warning", "critical"}:
                raise ValueError
        actual_refs = {
            ref for observation in observations
            for ref in (f"TOOL:{observation.tool}", observation.source_ref)
            if ref
        }
        actual_refs.update(
            f"TOOL:{step.step_id}" for step in plan.steps
            if any(item.status == "success" and policy.step_matcher(step, item) for item in observations)
        )
        if not set(report.observed_source_refs) <= actual_refs:
            raise ValueError
        if not isinstance(report.reference_evidence, dict) or not set(report.reference_evidence) <= actual_refs:
            raise ValueError
        if plan.status == "ready" and (report.status != "validated" or total == 0):
            reason = "policy_not_applicable"
            raise ValueError
        sufficient = (
            covered == total
            and report.allowed_conclusion_strength in {"supported", "supported_with_limits"}
            and not any(issue.severity == "critical" for issue in (*report.risks, *report.conflicts))
        ) if total else None
        if report.evidence_sufficient is True and sufficient is not True:
            raise ValueError
        return replace(
            report,
            assessment_status="checked",
            assessment_reason="plan_not_ready" if plan.status != "ready" else None,
            policy_ref=reference,
            evidence_sufficient=sufficient,
        )
    except Exception:  # noqa: BLE001 - stable, sanitized execution-boundary outcome
        return replace(
            validate_evidence(plan, None, []),
            assessment_status="check_failed",
            assessment_reason=reason,
            policy_ref=reference,
            allowed_conclusion_strength="insufficient",
            conclusion_guidance="证据检查不可用，不能形成已验证诊断；仅报告故障、可确认观测和下一步。",
        )
