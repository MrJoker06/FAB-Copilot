"""Controlled bridge from the lithography Skill to the existing named planner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..evidence.skill_policy import validate_skill_evidence
from ..evidence.validator import EvidenceValidation
from ..intent_runtime.contracts import IntentRoute
from ..manufacturing.named_playbooks import (
    NAMED_PLAYBOOK_VERSION,
    select_named_playbook,
)
from ..manufacturing.playbooks import PlaybookSelection
from ..planning_runtime.contracts import ExecutionPlan
from ..planning_runtime.named_planner import create_named_execution_plan


class LithoCpkWorkflowError(ValueError):
    """The trusted lithography workflow cannot form a safe existing plan."""


@dataclass(frozen=True, slots=True)
class LithoCpkWorkflow:
    """A fixed registry entry; it does not load code from a Skill package."""

    workflow_id: str = "litho-cpk-workflow"
    version: str = "2.0.0"
    evidence_policy_id: str = "capability-evidence"
    evidence_policy_version: str = "1.3.0"

    def __post_init__(self) -> None:
        if (
            self.workflow_id != "litho-cpk-workflow"
            or self.version != "2.0.0"
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
        return plan, selection

    @property
    def evidence_validator(self) -> Callable[..., EvidenceValidation]:
        return validate_skill_evidence
