"""Controlled bridge from the lithography Skill to the existing named planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ..evidence.skill_policy import validate_skill_evidence
from ..evidence.validator import EvidenceValidation
from ..intent_runtime.contracts import IntentRoute
from app.planning_runtime.named_playbooks import (
    NAMED_PLAYBOOK_VERSION,
    select_named_playbook,
)
from app.planning_runtime.playbook_contracts import PlaybookSelection
from ..planning_runtime.contracts import ExecutionPlan, PlanStep
from ..planning_runtime.named_planner import create_named_execution_plan

TREND_TOOL = "get_capability_trend"
_TREND_STEP_ID = "S05"


def _with_trend_step(plan: ExecutionPlan) -> ExecutionPlan:
    """Add the Skill's weekly trend as optional context after the Cpk step.

    The shared capability Playbook has no trend requirement, so the step carries
    no evidence id and cannot change required coverage or conclusion strength.
    """
    capability = next(
        (step for step in plan.steps if step.tool == "get_process_capability"), None
    )
    if capability is None or any(step.tool == TREND_TOOL for step in plan.steps):
        raise LithoCpkWorkflowError("named capability plan is invalid")
    parameters = {
        key: capability.parameters[key]
        for key in ("start", "end", "process_step")
        if key in capability.parameters
    }
    step = PlanStep(
        step_id=_TREND_STEP_ID,
        title="设备级 Cpk 周趋势",
        tool=TREND_TOOL,
        parameters=parameters,
        parameter_sources={
            key: capability.parameter_sources[key]
            for key in parameters
            if key in capability.parameter_sources
        },
        evidence_ids=(),
        depends_on=(capability.step_id,),
        required=False,
        success_criteria=(
            "时间范围和制程与能力步骤一致。",
            "按周区分 Cpk 是持续偏低还是集中在个别周。",
        ),
        estimated_result_limit=capability.estimated_result_limit,
        scope_role="primary",
        semantic_id="process_capability_cpk_trend",
        grain="equipment_week",
        filter_provenance=capability.filter_provenance,
        evidence_kind="metric",
        evidence_scope=capability.evidence_scope,
        evidence_start=capability.evidence_start,
        evidence_end=capability.evidence_end,
    )
    budget = plan.budget
    budget = replace(
        budget,
        planned_tool_calls=budget.planned_tool_calls + 1,
        max_tool_calls=budget.max_tool_calls + 1,
        per_tool_limits={**budget.per_tool_limits, TREND_TOOL: 2},
    )
    # The extended plan differs from the shared named plan, so it gets its own id.
    return replace(
        plan,
        plan_id=f"{plan.plan_id}-litho-trend",
        steps=(*plan.steps, step),
        budget=budget,
    )


class LithoCpkWorkflowError(ValueError):
    """The trusted lithography workflow cannot form a safe existing plan."""


@dataclass(frozen=True, slots=True)
class LithoCpkWorkflow:
    """A fixed registry entry; it does not load code from a Skill package."""

    workflow_id: str = "litho-cpk-workflow"
    version: str = "2.1.0"
    evidence_policy_id: str = "capability-evidence"
    evidence_policy_version: str = "1.3.0"

    def __post_init__(self) -> None:
        if (
            self.workflow_id != "litho-cpk-workflow"
            or self.version != "2.1.0"
            or self.evidence_policy_id != "capability-evidence"
            or self.evidence_policy_version != "1.3.0"
        ):
            raise LithoCpkWorkflowError("controlled workflow identity is fixed")

    def build(
        self, question: str, route: IntentRoute
    ) -> tuple[ExecutionPlan, PlaybookSelection]:
        if (
            not isinstance(question, str)
            or not question.strip()
            or not isinstance(route, IntentRoute)
            or route.intent != "capability_excursion"
            or route.clarification_needed
            or route.process_steps != ("LITHO",)
            or route.scope_resolution.scope_type != "process"
            or route.scope_resolution.resolved_ids != ("LITHO",)
        ):
            raise LithoCpkWorkflowError("lithography scope is not supported")
        selection = select_named_playbook(route)
        plan = create_named_execution_plan(question, route, selection)
        playbook = selection.selected_playbook
        if (
            selection.status != "selected"
            or playbook is None
            or playbook.playbook_id != "PB-CAPABILITY-001"
            or playbook.playbook_version != NAMED_PLAYBOOK_VERSION
            or plan.status != "ready"
            or plan.schema_version != "1.2"
            or plan.planner_version != NAMED_PLAYBOOK_VERSION
            or any("sql" in step.parameters for step in plan.steps)
        ):
            raise LithoCpkWorkflowError("named capability plan is invalid")
        return _with_trend_step(plan), selection

    @property
    def evidence_validator(self) -> Callable[..., EvidenceValidation]:
        return validate_skill_evidence
