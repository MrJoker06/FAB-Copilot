"""Offline acceptance demonstration for the opt-in lithography Cpk Skill."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.loop_response import classify_loop_response
from ..agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolSource,
    ToolSourceKind,
)
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from ..evidence.validator import EvidenceObservation
from ..integrations.knowledge.fake_search import FakeKnowledgeSearchAdapter
from ..integrations.manufacturing.fake_operational_reports import (
    FakeOperationalReportsAdapter,
)
from app.demo_data.tool_sources.process_diagnostics import (
    FakeProcessDiagnosticsAdapter,
)
from ..intent_runtime.routing import route_question
from ..knowledge.decision import usable_result
from ..knowledge.search_tool.binding import create_knowledge_search_binding
from ..knowledge.search_tool.contracts import (
    KnowledgeSearchInput,
    KnowledgeSearchSnapshot,
    knowledge_scope,
)
from ..manufacturing.operational_reports.binding import create_recent_excursions_binding
from ..manufacturing.operational_reports.contracts import RecentExcursionsInput
from app.tools.process_diagnostics.binding import (
    create_process_capability_binding,
    create_sensor_summary_binding,
)
from app.tools.process_diagnostics.contracts import (
    ProcessCapabilityInput,
    SensorSummaryInput,
)
from ..tools.capability_trend.contracts import CapabilityTrendInput
from app.demo_data.tool_sources.capability_trend import FakeCapabilityTrendSource
from ..tools.capability_trend.tool import create_capability_trend_binding
from .agent_assembly import assemble_agent
from .litho_cpk_workflow import LithoCpkWorkflow
from .loop_assembly import bind_loop_run
from .ready_assembly import bind_ready_run
from .skill_assembly import SkillAssemblyConfiguration, SkillExecutionRequest

_QUESTION = "分析 LITHO 在 2026-10-01 到 2026-10-08 的 Cpk 和制程异常"
_TOOLS = (
    "get_process_capability",
    "get_capability_trend",
    "get_recent_excursions",
    "get_sensor_summary",
    "search_knowledge",
)


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("analyst",)


class _Events:
    async def emit(self, _event: object) -> None:
        return None


class _ReadyModel:
    async def complete(
        self, _request: ModelRequest, _context: RuntimeContext
    ) -> ModelResponse:
        raise AssertionError("Ready execution must not invoke the model")


class _LoopModel:
    def __init__(self, plan: object) -> None:
        self._plan = plan
        self._calls = 0
        self.requests: list[ModelRequest] = []

    async def complete(
        self, request: ModelRequest, _context: RuntimeContext
    ) -> ModelResponse:
        self._calls += 1
        self.requests.append(request)
        if self._calls == 1:
            return ModelResponse(
                tool_calls=tuple(
                    ModelToolCall(str(index), step.tool, json.dumps(step.parameters))
                    for index, step in enumerate(self._plan.steps, 1)
                )
            )
        if self._calls == 2 and any(
            message.role == "tool" for message in request.messages
        ):
            return ModelResponse(content="Fixed lithography Cpk fixture completed.")
        raise AssertionError("unexpected lithography Loop model sequence")


def _diagnostics_rows(tool: str) -> tuple[dict[str, object], ...]:
    if tool == "get_sensor_summary":
        return (
            {
                "process_step": "LITHO",
                "equipment_id": "LITHO-01",
                "signal_name": "focus",
                "signal_unit": "nm",
                "samples": 40,
                "missing_samples": 0,
                "flagged_outliers": 1,
                "mean_value": 10.5,
                "min_value": 10.0,
                "max_value": 11.0,
            },
        )
    return (
        {
            "process_step": "LITHO",
            "equipment_id": "LITHO-01",
            "samples": 40,
            "mean_value": 10.5,
            "sigma": 0.5,
            "min_value": 10.0,
            "max_value": 11.0,
            "cpk": 1.0,
            "metric_name": "cd",
            "metric_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 12.0,
        },
    )


def _trend_rows() -> tuple[dict[str, object], ...]:
    common = {
        "process_step": "LITHO",
        "equipment_id": "LITHO-01",
        "metric_name": "cd",
        "metric_unit": "nm",
        "spec_lsl": 9.0,
        "spec_usl": 12.0,
    }
    return (
        {
            "week_start": "2026-09-28",
            "period_start": "2026-10-01",
            "period_end": "2026-10-04",
            "samples": 20,
            "mean_value": 10.5,
            "sigma": 0.3,
            "cpk": 1.67,
            **common,
        },
        {
            "week_start": "2026-10-05",
            "period_start": "2026-10-05",
            "period_end": "2026-10-08",
            "samples": 20,
            "mean_value": 10.5,
            "sigma": 0.6,
            "cpk": 0.83,
            **common,
        },
    )


def _excursion_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "run_time": "2026-10-08",
            "lot_id": "LOT-LITHO-001",
            "process_step": "LITHO",
            "equipment_id": "LITHO-01",
            "excursion_code": "E001",
            "thickness_nm": 10.0,
            "uniformity_pct": 1.0,
            "defect_density": 0.1,
            "measurement_name": "cd",
            "measurement_value": 10.0,
            "measurement_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 12.0,
        },
    )


def _bindings(plan: object, as_of: date, principal: _Principal):
    steps = {step.tool: step for step in plan.steps}
    capability = ProcessCapabilityInput.from_arguments(
        steps["get_process_capability"].parameters
    ).resolve(as_of)
    sensors = SensorSummaryInput.from_arguments(
        steps["get_sensor_summary"].parameters
    ).resolve(as_of)
    trend = CapabilityTrendInput.from_arguments(
        steps["get_capability_trend"].parameters
    ).resolve(as_of)
    trends = FakeCapabilityTrendSource("demo", {trend: _trend_rows()})
    excursions = RecentExcursionsInput.from_arguments(
        steps["get_recent_excursions"].parameters
    ).resolve(as_of)
    diagnostics = FakeProcessDiagnosticsAdapter(
        "demo",
        {
            capability: _diagnostics_rows("get_process_capability"),
            sensors: _diagnostics_rows("get_sensor_summary"),
        },
    )
    reports = FakeOperationalReportsAdapter("demo", {excursions: _excursion_rows()})
    query = KnowledgeSearchInput.from_arguments(
        steps["search_knowledge"].parameters
    ).resolve()
    sources = tuple(
        ToolSource(
            f"fake:knowledge-search/{kind}",
            "fake-knowledge-search",
            ToolSourceKind.FAKE,
            knowledge_scope(principal),
        )
        for kind in query.source_types
    )
    snapshot = KnowledgeSearchSnapshot(
        query,
        "demo",
        "engineer",
        "engineer",
        {"Cpk": ("cpk",)},
        (
            {
                "source_type": "knowledge",
                "reference_id": "KB-LITHO-001",
                "status": "Active",
                "source": "FAKE control plan",
                "title": "LITHO Cpk response",
                "section": "response",
                "process_steps": "LITHO",
                "authority": 5,
                "tags": "litho",
                "score": -1.0,
            },
        ),
        sources,
    )
    knowledge = FakeKnowledgeSearchAdapter("demo", "engineer", {query: snapshot})
    return (
        create_process_capability_binding(diagnostics, today=lambda: as_of),
        create_recent_excursions_binding(reports, today=lambda: as_of),
        create_sensor_summary_binding(diagnostics, today=lambda: as_of),
        create_knowledge_search_binding(knowledge, default_tenant_id="demo"),
        create_capability_trend_binding(trends, today=lambda: as_of),
    ), (diagnostics, reports, knowledge, trends)


async def run_litho_cpk_demo(
    mode: str = "ready",
    *,
    role: str = "analyst",
    package_root: str | None = None,
    resources: tuple[str, ...] = (),
) -> dict[str, object]:
    """Run the real named plan with fixture-backed native ports only."""
    if mode not in {"ready", "loop"}:
        raise ValueError("mode must be ready or loop")
    as_of = date(2026, 10, 31)
    route = route_question(_QUESTION, as_of)
    workflow = LithoCpkWorkflow()
    provisional_plan, _ = workflow.build(_QUESTION, route)
    principal = _Principal(roles=(role,))
    bindings, adapters = _bindings(provisional_plan, as_of, principal)
    definition = AgentDefinition(
        "litho-cpk-demo",
        "1.0.0",
        "analyst",
        "Run the controlled lithography Cpk Skill.",
        tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
        ComponentReference("litho-demo-model", "1.0.0"),
        ComponentReference("litho-demo-policy", "1.0.0"),
        (ComponentReference("litho-cpk-diagnostic", "1.1.0"),),
    )
    default_root = str(
        Path(__file__).resolve().parents[1] / "skills" / "litho-cpk-diagnostic"
    )
    configuration = SkillAssemblyConfiguration(
        (package_root or default_root,), (workflow,)
    )
    request = SkillExecutionRequest(_QUESTION, route, mode, resources)
    holder: dict[str, object] = {}

    def budget_factory() -> LoopGuardToolBudget:
        guard = ToolLoopGuard(app.skill_binding.plan)
        holder["guard"] = guard
        return LoopGuardToolBudget(guard)

    app = assemble_agent(
        definition,
        model=(_ReadyModel() if mode == "ready" else _LoopModel(provisional_plan)),
        events=_Events(),
        bindings=bindings,
        policy=DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
        ),
        budget_factory=budget_factory,
        server_capabilities=frozenset(_TOOLS),
        model_policy_ref=ComponentReference("litho-demo-model", "1.0.0"),
        policy_ref=ComponentReference("litho-demo-policy", "1.0.0"),
        skill_configuration=configuration,
        skill_request=request,
    )
    plan = app.skill_binding.plan
    context = RuntimeContext(
        principal,
        f"litho-cpk-{mode}",
        ToolExecutionLimits(20, 100, time.monotonic() + 5),
    )
    projector = ReadyResultPolicy(
        knowledge_tools=frozenset({"search_knowledge"}),
        usable_knowledge_result=usable_result,
    )
    run = app.new_run(context, result_policy=projector)
    guard = holder["guard"]
    if not isinstance(guard, ToolLoopGuard):
        raise TypeError("lithography Skill guard is unavailable")
    binding = (
        bind_ready_run(plan, guard, run, projector)
        if mode == "ready"
        else bind_loop_run(plan, guard, run, projector)
    )

    async def notify(_progress: object, _event: dict[str, object]) -> None:
        return None

    if mode == "ready":
        outcome = await execute_dispatched_ready_plan(
            plan,
            guard,
            context.run_id,
            None,
            binding=binding,
            notify=notify,
            emit_event=lambda *_args, **_kwargs: None,
        )
        observations = tuple(
            EvidenceObservation(**item) for item in outcome.observation_payloads
        )
        trace = outcome.trace
    else:
        first = await run.model_stage(
            call_id="litho-model-1", messages=(ModelMessage("user", _QUESTION),)
        )
        response = classify_loop_response(first.value)
        outcome = await execute_dispatched_loop_round(
            plan,
            guard,
            context.run_id,
            1,
            response,
            None,
            binding=binding,
            notify=notify,
            emit_event=lambda *_args, **_kwargs: None,
        )
        second_messages = (
            ModelMessage("user", _QUESTION),
            ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
            *(
                ModelMessage("tool", item["content"], tool_call_id=item["tool_call_id"])
                for item in outcome.tool_messages
            ),
        )
        await run.model_stage(
            call_id="litho-model-2",
            messages=second_messages,
        )
        observations = tuple(
            EvidenceObservation(**item) for item in outcome.observation_payloads
        )
        trace = outcome.trace
    evidence = app.skill_binding.check_evidence(list(observations))
    return {
        "plan": plan,
        "trace": trace,
        "observations": observations,
        "playbook": app.skill_binding.selection.selected_playbook,
        "evidence": evidence,
        "validation": evidence.validation,
        "metadata": dict(run.skill_metadata),
        "model_context": run.skill_context,
        "model_calls": getattr(app.model, "_calls", 0),
        "model_requests": tuple(getattr(app.model, "requests", ())),
        "guard": guard,
        "source_calls": {
            "process_diagnostics": len(adapters[0].calls),
            "operational_reports": len(adapters[1].calls),
            "knowledge_search": len(adapters[2].calls),
            "capability_trend": len(adapters[3].calls),
        },
    }


def run_litho_cpk_demo_sync(mode: str = "ready", **kwargs: object) -> dict[str, object]:
    return asyncio.run(run_litho_cpk_demo(mode, **kwargs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--resource", action="append", default=[])
    parser.add_argument("--package-root")
    args = parser.parse_args(argv)
    try:
        result = run_litho_cpk_demo_sync(
            args.mode,
            role=args.role,
            package_root=args.package_root,
            resources=tuple(args.resource),
        )
    except (ValueError, RuntimeError):
        print(
            json.dumps(
                {"error": "Lithography Skill demo is unavailable."}, ensure_ascii=False
            )
        )
        return 2
    payload = {
        "mode": args.mode,
        "plan": {
            "id": result["plan"].plan_id,
            "steps": [
                {
                    "id": step.step_id,
                    "tool": step.tool,
                    "depends_on": list(step.depends_on),
                    "evidence_ids": list(step.evidence_ids),
                }
                for step in result["plan"].steps
            ],
        },
        "typed_results": [
            {
                "tool": item["tool"],
                "status": item["status"],
                "rows": item.get("rows", 0),
                "sources": item.get("sources", ()),
            }
            for item in result["trace"]
        ],
        "metadata": result["metadata"],
        "model_calls": result["model_calls"],
        "source_calls": result["source_calls"],
        "guard": result["guard"].summary(),
        "evidence_status": result["evidence"].status,
        "evidence_sufficient": result["evidence"].evidence_sufficient,
        "validation": (
            result["validation"].to_dict() if result["validation"] is not None else None
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if all(item["status"] == "ok" for item in result["trace"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
