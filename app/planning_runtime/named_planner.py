"""Versioned deterministic planner for the named-query capability."""

from __future__ import annotations

from dataclasses import replace

from ..intent_runtime.contracts import IntentRoute
from ..manufacturing.named_playbooks import (
    NAMED_DOMAIN_PLAYBOOKS,
    NAMED_PLAYBOOK_VERSION,
    NAMED_QUERY_CAPABILITY_ID,
    NAMED_QUERY_CAPABILITY_VERSION,
    select_named_playbook,
)
from ..manufacturing.playbooks import PlaybookSelection
from .contracts import ExecutionPlan
from .service import create_execution_plan


class NamedPlannerError(ValueError):
    """The supplied playbook cannot safely form a named-query plan."""


def _valid_selection(selection: PlaybookSelection) -> bool:
    playbook = selection.selected_playbook
    if selection.status != "selected":
        return playbook is None
    return (
        playbook is not None
        and NAMED_DOMAIN_PLAYBOOKS.get(playbook.intent) is playbook
        and playbook.playbook_version == NAMED_PLAYBOOK_VERSION
        and playbook.schema_version == "2.0"
    )


def create_named_execution_plan(
    question: str, route: IntentRoute, selection: PlaybookSelection | None = None
) -> ExecutionPlan:
    canonical = select_named_playbook(route)
    selection = canonical if selection is None else selection
    if selection != canonical or not _valid_selection(selection):
        raise NamedPlannerError("named planner requires a declared v2 playbook")
    plan = create_execution_plan(question, route, selection)
    if any(
        step.tool == "query_manufacturing_data"
        or "sql" in step.parameters
        or "sql" in step.parameter_sources
        for step in plan.steps
    ):
        raise NamedPlannerError("named planner produced a SQL capability")
    budget = plan.budget
    budget = replace(
        budget,
        per_tool_limits={
            name: value
            for name, value in budget.per_tool_limits.items()
            if name != "query_manufacturing_data"
        },
    )
    return replace(
        plan,
        plan_id=f"named-{NAMED_QUERY_CAPABILITY_VERSION}-{plan.plan_id}",
        schema_version="1.2",
        planner_version=NAMED_PLAYBOOK_VERSION,
        budget=budget,
    )


__all__ = [
    "NAMED_QUERY_CAPABILITY_ID",
    "NAMED_QUERY_CAPABILITY_VERSION",
    "NamedPlannerError",
    "create_named_execution_plan",
]
