"""Run native operational-report tools through Ready or Loop dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

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
    RuntimeEvent,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.demo_data.tool_sources.operational_reports import (
    FakeOperationalReportsAdapter,
)
from app.tools.operational_reports.data_source import (
    SQLiteOperationalReportsAdapter,
)
from app.tools.operational_reports.binding import (
    create_defect_pareto_binding,
    create_equipment_productivity_binding,
    create_recent_excursions_binding,
)
from app.tools.operational_reports.contracts import (
    DefectParetoInput,
    EquipmentProductivityInput,
    OperationalReportInputError,
    RecentExcursionsInput,
)
from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)
from .agent_assembly import AssemblyError, assemble_agent
from .loop_assembly import bind_loop_run
from .ready_assembly import bind_ready_run

_TOOLS = ("get_equipment_productivity", "get_defect_pareto", "get_recent_excursions")


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


@dataclass(slots=True)
class _Events:
    items: list[RuntimeEvent]

    async def emit(self, event: RuntimeEvent) -> None:
        self.items.append(event)


class _ReadyModel:
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        del request, context
        raise AssertionError("Ready execution must not select tools through the model")


@dataclass(slots=True)
class _LoopModel:
    tool: str
    arguments: str
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        del context
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall("operational-tool-1", self.tool, self.arguments),
                )
            )
        if len(self.requests) == 2:
            messages = [
                item
                for item in request.messages
                if item.role == "tool" and item.tool_call_id == "operational-tool-1"
            ]
            if len(messages) != 1:
                raise AssertionError(
                    "operational Loop fixture requires its tool message"
                )
            try:
                payload = json.loads(messages[0].content)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AssertionError(
                    "operational Loop fixture requires JSON tool data"
                ) from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("ok"), bool)
                or "data" not in payload
                or not isinstance(payload.get("execution_state"), str)
            ):
                raise AssertionError(
                    "operational Loop fixture received inconsistent tool data"
                )
            return ModelResponse(
                content="Fixed operational report Loop fixture completed."
            )
        raise AssertionError("unexpected operational report Loop sequence")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    parser.add_argument("--equipment-db")
    parser.add_argument("--quality-db")
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default=_TOOLS[0])
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of", default="2026-10-24")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


def _input(
    tool: str,
) -> (
    type[EquipmentProductivityInput | DefectParetoInput | RecentExcursionsInput] | None
):
    return {
        "get_equipment_productivity": EquipmentProductivityInput,
        "get_defect_pareto": DefectParetoInput,
        "get_recent_excursions": RecentExcursionsInput,
    }.get(tool)


def _fixture(tool: str, query: Any) -> tuple[dict[str, object], ...]:
    if tool == "get_equipment_productivity":
        equipment = query.equipment_id or f"{query.process_step or 'CMP'}-01"
        return (
            {
                "equipment_id": equipment,
                "recorded_minutes": 10.0,
                "productive_minutes": 8.0,
                "productive_pct": 80.0,
                "unscheduled_down_minutes": 1.0,
                "scheduled_down_minutes": 1.0,
            },
        )
    if tool == "get_defect_pareto":
        return (
            {
                "defect_type": "Particle",
                "process_steps": query.process_step or "CMP",
                "defect_count": 4,
                "affected_lots": 2,
                "share_pct": 100.0,
            },
        )
    return (
        {
            "run_time": query.end.isoformat(),
            "lot_id": "LOT-001",
            "process_step": query.process_step or "CMP",
            "equipment_id": query.equipment_id or "CMP-01",
            "excursion_code": "E001",
            "thickness_nm": 10.0,
            "uniformity_pct": 1.0,
            "defect_density": 0.1,
            "measurement_name": "thickness",
            "measurement_value": 10.0,
            "measurement_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 11.0,
        },
    )


def _fake(
    tenant: str, as_of: date, tool: str, arguments: dict[str, object]
) -> FakeOperationalReportsAdapter:
    model = _input(tool)
    try:
        query = model.from_arguments(arguments).resolve(as_of) if model else None
        return FakeOperationalReportsAdapter(
            tenant, {query: _fixture(tool, query)} if query else {}
        )
    except OperationalReportInputError:
        return FakeOperationalReportsAdapter(tenant, {})


def _plan(tool: str, arguments: dict[str, object], max_calls: int) -> ExecutionPlan:
    return ExecutionPlan(
        "operational-reports-demo",
        "1",
        "demo",
        "ready",
        "",
        "",
        None,
        None,
        AnalysisScopeContract("manufacturing", (), (), ()),
        (),
        (
            PlanStep(
                "S01",
                "Operational report",
                tool,
                arguments,
                {},
                (),
                (),
                True,
                (),
                100,
                "primary",
            ),
        ),
        PlanBudget(
            max_calls, max_calls, 2, 100, {name: max_calls for name in _TOOLS}, 1, 1
        ),
        (),
        (),
    )


def _application(
    args: argparse.Namespace,
    as_of: date,
    adapter: FakeOperationalReportsAdapter | SQLiteOperationalReportsAdapter,
    guard: ToolLoopGuard,
    context: RuntimeContext,
    model: _ReadyModel | _LoopModel,
):
    definition = AgentDefinition(
        "operational-reports-demo",
        "1.0.0",
        "analyst",
        "Run approved operational reports.",
        tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
        ComponentReference("operational-reports-demo-model", "1.0.0"),
        ComponentReference("operational-reports-demo-policy", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    application = assemble_agent(
        definition,
        model=model,
        events=_Events([]),
        bindings=(
            create_equipment_productivity_binding(adapter, today=lambda: as_of),
            create_defect_pareto_binding(adapter, today=lambda: as_of),
            create_recent_excursions_binding(adapter, today=lambda: as_of),
        ),
        policy=DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id=args.source_tenant_id
        ),
        budget_factory=lambda: LoopGuardToolBudget(guard),
        server_capabilities=frozenset(_TOOLS),
        model_policy_ref=ComponentReference("operational-reports-demo-model", "1.0.0"),
        policy_ref=ComponentReference("operational-reports-demo-policy", "1.0.0"),
    )
    return application.new_run(context, result_policy=projector), projector


def _typed(result: Any) -> dict[str, object]:
    return {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "version": result.tool_version,
        "status": result.status.value,
        "state": result.execution_state.value,
        "execution_state": result.execution_state.value,
        "row_count": result.row_count,
        "data": result.data,
        "error": None
        if result.error is None
        else {
            "code": result.error.code,
            "kind": result.error.kind.value,
            "public_message": result.error.public_message,
        },
    }


def _safe_plan(plan: ExecutionPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "steps": [
            {
                "step_id": item.step_id,
                "tool": item.tool,
                "depends_on": list(item.depends_on),
            }
            for item in plan.steps
        ],
        "budget": {
            "max_tool_calls": plan.budget.max_tool_calls,
            "max_rows_per_call": plan.budget.max_rows_per_call,
            "per_tool_limits": dict(plan.budget.per_tool_limits),
        },
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        as_of, arguments = date.fromisoformat(args.as_of), json.loads(args.arguments)
        if (
            not isinstance(arguments, dict)
            or args.timeout_ms < 0
            or args.max_tool_calls < 0
        ):
            raise ValueError("invalid operator arguments")
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    if args.adapter == "sqlite":
        required = {
            "get_equipment_productivity": ("equipment", args.equipment_db),
            "get_defect_pareto": ("quality", args.quality_db),
            "get_recent_excursions": ("manufacturing", args.manufacturing_db),
        }.get(args.tool)
        if required is None:
            selected_path = (
                args.manufacturing_db or args.equipment_db or args.quality_db
            )
        else:
            selected_path = required[1]
        if not selected_path:
            return {
                "error": f"SQLite adapter requires the {required[0] if required else 'selected'} database."
            }
        adapter = SQLiteOperationalReportsAdapter(
            equipment_path=args.equipment_db
            if args.tool == "get_equipment_productivity"
            else None,
            quality_path=args.quality_db if args.tool == "get_defect_pareto" else None,
            manufacturing_path=args.manufacturing_db
            if args.tool == "get_recent_excursions"
            else None,
            demo_tenant_id=args.source_tenant_id,
        )
        adapter_kind = "sqlite"
    else:
        adapter, adapter_kind = (
            _fake(args.source_tenant_id, as_of, args.tool, arguments),
            "fake",
        )
    plan = _plan(args.tool, arguments, args.max_tool_calls)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        f"operational-{args.mode}-demo",
        ToolExecutionLimits(
            args.max_tool_calls, 100, time.monotonic() + args.timeout_ms / 1000
        ),
    )
    model: _ReadyModel | _LoopModel = (
        _ReadyModel()
        if args.mode == "ready"
        else _LoopModel(args.tool, json.dumps(arguments, ensure_ascii=False))
    )
    try:
        run, projector = _application(args, as_of, adapter, guard, context, model)
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    progress: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def notify(_progress: object, event: dict[str, object]) -> None:
        progress.append(
            {key: value for key, value in event.items() if key != "arguments"}
        )

    def emit_event(name: str, run_id: str, **details: object) -> None:
        events.append({"event": name, "run_id": run_id, **details})

    if args.mode == "ready":
        outcome = await execute_dispatched_ready_plan(
            plan,
            guard,
            context.run_id,
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages: list[dict[str, str]] = []
        final = None
    else:
        first = await run.model_stage(
            call_id="operational-model-1",
            messages=(ModelMessage("user", "Run fixed operational report."),),
        )
        outcome = await execute_dispatched_loop_round(
            plan,
            guard,
            context.run_id,
            1,
            classify_loop_response(first.value),
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages = list(outcome.tool_messages)
        second = await run.model_stage(
            call_id="operational-model-2",
            messages=(
                ModelMessage("user", "Run fixed operational report."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage(
                        "tool", item["content"], tool_call_id=item["tool_call_id"]
                    )
                    for item in messages
                ),
            ),
        )
        final = classify_loop_response(second.value).content
    sources = {
        source["source_ref"]: source
        for item in outcome.trace
        for source in item.get("sources", ())
    }
    return {
        "mode": args.mode,
        "adapter_kind": adapter_kind,
        "plan": _safe_plan(plan),
        "typed_results": [_typed(item) for item in outcome.tool_results],
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": sources,
        "tool_messages": messages,
        "final_response": final,
        "guard": guard.summary(),
        "model_tool_selection_calls": 0 if args.mode == "ready" else 1,
        "model_response_calls": 0 if args.mode == "ready" else len(model.requests),
        "progress": progress,
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        payload = asyncio.run(_run(_parser().parse_args(argv)))
    except Exception:  # noqa: BLE001
        payload = {"error": "INTERNAL_ERROR"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    return (
        0
        if payload.get("typed_results", [{}])[0].get("status")
        == ToolStatus.SUCCEEDED.value
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
