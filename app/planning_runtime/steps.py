from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..manufacturing.playbooks import DomainPlaybook, EvidenceRequirement
from ..intent_runtime.contracts import IntentRoute
from .contracts import PlanBudget, PlanStep
from .queries import _base_parameters, _manufacturing_queries
from .scope import _scope_role, _step_scope, _step_semantics, _target_scope


@dataclass
class _StepBuilder:
    titles: list[str]
    tool: str
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    evidence_ids: list[str]
    dependency_keys: list[str]
    required: bool
    success_criteria: list[str]
    estimated_result_limit: int


def _result_limit(tool: str, parameters: dict[str, Any]) -> int:
    if tool == "search_knowledge":
        return int(parameters.get("limit", 10))
    if tool == "get_defect_pareto":
        return int(parameters.get("limit", 25))
    if tool == "get_recent_excursions":
        return int(parameters.get("limit", 100))
    return 100


def _tool_invocations(
    question: str,
    route: IntentRoute,
    resolved: dict[str, Any],
    evidence: EvidenceRequirement,
) -> tuple[tuple[str, str, dict[str, Any], dict[str, str]], ...]:
    invocations: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
    for tool in evidence.source_tools:
        if tool == "get_process_pass_rate" and not route.process_steps:
            # This optional evidence only has a meaningful, fixed scope when a
            # route resolved a process.  Do not call it as an unfiltered proxy.
            continue
        if tool == "query_manufacturing_data":
            for title, sql in _manufacturing_queries(evidence.evidence_id, route, resolved):
                invocations.append((
                    tool,
                    title,
                    {"sql": sql},
                    {"sql": f"planner.template.{evidence.evidence_id}"},
                ))
            continue
        parameters, sources = _base_parameters(tool, question, route, evidence)
        if tool == "get_yield_trend" and route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
            parameters["product"] = route.scope_resolution.resolved_ids[0]
            sources["product"] = "intent_route.scope_resolution"
        invocations.append((tool, evidence.name, parameters, sources))
    return tuple(invocations)


def _ready_steps(
    question: str,
    route: IntentRoute,
    playbook: DomainPlaybook,
    resolved: dict[str, Any],
) -> tuple[PlanStep, ...]:
    builders: dict[str, _StepBuilder] = {}
    previous_required_group_keys: tuple[str, ...] = ()

    for evidence in playbook.evidence_requirements:
        current_group_keys: list[str] = []
        for tool, title, parameters, parameter_sources in _tool_invocations(question, route, resolved, evidence):
            key = json.dumps({"tool": tool, "parameters": parameters}, ensure_ascii=False, sort_keys=True)
            current_group_keys.append(key)
            builder = builders.get(key)
            if builder is None:
                builder = _StepBuilder(
                    titles=[],
                    tool=tool,
                    parameters=parameters,
                    parameter_sources=parameter_sources,
                    evidence_ids=[],
                    dependency_keys=[],
                    required=False,
                    success_criteria=[],
                    estimated_result_limit=_result_limit(tool, parameters),
                )
                builders[key] = builder
            if title not in builder.titles:
                builder.titles.append(title)
            if evidence.evidence_id not in builder.evidence_ids:
                builder.evidence_ids.append(evidence.evidence_id)
            for dependency_key in previous_required_group_keys:
                if dependency_key != key and dependency_key not in builder.dependency_keys:
                    builder.dependency_keys.append(dependency_key)
            builder.required = builder.required or evidence.required or (
                evidence.evidence_id == "YLD-05" and route.scope_resolution.scope_type in {"process", "equipment"}
            )
            for criterion in evidence.acceptance_criteria:
                if criterion not in builder.success_criteria:
                    builder.success_criteria.append(criterion)
        if current_group_keys and evidence.required:
            previous_required_group_keys = tuple(dict.fromkeys(current_group_keys))

    key_to_step_id = {key: f"S{index:02d}" for index, key in enumerate(builders, start=1)}
    return tuple(
        PlanStep(
            step_id=key_to_step_id[key],
            title=" / ".join(builder.titles),
            tool=builder.tool,
            parameters=builder.parameters,
            parameter_sources=builder.parameter_sources,
            evidence_ids=tuple(builder.evidence_ids),
            depends_on=tuple(key_to_step_id[item] for item in builder.dependency_keys),
            required=builder.required,
            success_criteria=tuple(builder.success_criteria),
            estimated_result_limit=builder.estimated_result_limit,
            scope_role=_scope_role(_step_scope(builder.tool, builder.parameters, tuple(builder.evidence_ids)), _target_scope(route, resolved)),
            evidence_kind=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[0],
            semantic_id=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[1],
            grain=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[2],
            evidence_scope=_step_scope(builder.tool, builder.parameters, tuple(builder.evidence_ids)),
            evidence_start=route.time_range.start if (builder.tool != "query_manufacturing_data" or " >= '" in str(builder.parameters.get("sql", ""))) and builder.tool not in {"search_knowledge"} else None,
            evidence_end=route.time_range.end if (builder.tool != "query_manufacturing_data" or " < '" in str(builder.parameters.get("sql", ""))) and builder.tool not in {"search_knowledge"} else None,
        )
        for key, builder in builders.items()
    )


def _empty_budget() -> PlanBudget:
    return PlanBudget(
        planned_tool_calls=0,
        max_tool_calls=0,
        max_model_iterations=1,
        max_rows_per_call=100,
        per_tool_limits={},
        max_identical_parameter_calls=0,
        max_no_progress_rounds=1,
    )


def _generic_budget() -> PlanBudget:
    return PlanBudget(
        planned_tool_calls=0,
        max_tool_calls=10,
        max_model_iterations=6,
        max_rows_per_call=100,
        per_tool_limits={"*": 3, "search_knowledge": 6, "query_manufacturing_data": 5},
        max_identical_parameter_calls=1,
        max_no_progress_rounds=2,
    )
