"""Run native process-diagnostics tools through the Ready or Loop dispatcher."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import date

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
from ..integrations.manufacturing.fake_process_diagnostics import (
    FakeProcessDiagnosticsAdapter,
)
from ..integrations.manufacturing.sqlite_process_diagnostics import (
    SQLiteProcessDiagnosticsAdapter,
)
from ..manufacturing.process_diagnostics.binding import (
    create_process_capability_binding,
    create_sensor_summary_binding,
)
from ..manufacturing.process_diagnostics.contracts import (
    DiagnosticsInputError,
    DiagnosticsQuery,
    ProcessCapabilityInput,
    SensorSummaryInput,
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

_CAPABILITY = "get_process_capability"
_SENSORS = "get_sensor_summary"
_NATIVE_TOOLS = frozenset({_CAPABILITY, _SENSORS})


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


class _NeverSelectModel:
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        del request, context
        raise AssertionError("Ready execution must not select tools through the model")


@dataclass(slots=True)
class _TwoResponseModel:
    """A fixed model that selects once and consumes the resulting tool message."""

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
                    ModelToolCall("diagnostics-tool-1", self.tool, self.arguments),
                )
            )
        if len(self.requests) == 2 and any(
            item.role == "tool" and item.tool_call_id == "diagnostics-tool-1"
            for item in request.messages
        ):
            return ModelResponse(content="Fixed diagnostics Loop fixture completed.")
        raise AssertionError("unexpected diagnostics Loop model sequence")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--equipment-db")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default=_CAPABILITY)
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of", default="2026-10-24")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


def _plan(tool: str, arguments: dict[str, object], max_calls: int) -> ExecutionPlan:
    return ExecutionPlan(
        "diagnostics-demo",
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
                "Process diagnostics",
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
            max_calls,
            max_calls,
            2,
            100,
            {_CAPABILITY: max_calls, _SENSORS: max_calls},
            1,
            1,
        ),
        (),
        (),
    )


def _fake_rows(tool: str) -> tuple[dict[str, object], ...]:
    if tool == _SENSORS:
        return (
            {
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "signal_name": "pressure",
                "signal_unit": "kPa",
                "samples": 4,
                "missing_samples": 0,
                "flagged_outliers": 1,
                "mean_value": 10.5,
                "min_value": 10.0,
                "max_value": 11.0,
            },
        )
    return (
        {
            "process_step": "CMP",
            "equipment_id": "CMP-01",
            "samples": 4,
            "mean_value": 10.5,
            "sigma": 0.5,
            "min_value": 10.0,
            "max_value": 11.0,
            "cpk": 1.0,
            "metric_name": "thickness",
            "metric_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 12.0,
        },
    )


def _fake_adapter(
    tenant: str, as_of: date, tool: str, arguments: dict[str, object]
) -> FakeProcessDiagnosticsAdapter:
    try:
        query: DiagnosticsQuery
        if tool == _CAPABILITY:
            query = ProcessCapabilityInput.from_arguments(arguments).resolve(as_of)
        elif tool == _SENSORS:
            query = SensorSummaryInput.from_arguments(arguments).resolve(as_of)
        else:
            return FakeProcessDiagnosticsAdapter(tenant, {})
        return FakeProcessDiagnosticsAdapter(tenant, {query: _fake_rows(tool)})
    except DiagnosticsInputError:
        return FakeProcessDiagnosticsAdapter(tenant, {})


def _typed_result(result: object) -> dict[str, object]:
    return {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "version": result.tool_version,
        "status": result.status.value,
        "state": result.execution_state.value,
        "execution_state": result.execution_state.value,
        "row_count": result.row_count,
        "data": result.data,
        "error": (
            {
                "code": result.error.code,
                "kind": result.error.kind.value,
                "public_message": result.error.public_message,
            }
            if result.error
            else None
        ),
    }


def _safe_plan(plan: ExecutionPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "depends_on": list(step.depends_on),
            }
            for step in plan.steps
        ],
        "budget": {
            "max_tool_calls": plan.budget.max_tool_calls,
            "max_rows_per_call": plan.budget.max_rows_per_call,
            "per_tool_limits": dict(plan.budget.per_tool_limits),
        },
    }


def _source_scopes(trace: list[dict]) -> dict[str, dict]:
    """Expose the dispatcher projection's authoritative ToolSource scopes."""
    values: dict[str, dict] = {}
    for item in trace:
        for source in item.get("sources", ()):
            if isinstance(source, dict) and isinstance(source.get("source_ref"), str):
                values[source["source_ref"]] = dict(source)
    return values


def _adapter(args: argparse.Namespace, as_of: date, arguments: dict[str, object]):
    if args.adapter == "fake":
        return _fake_adapter(args.source_tenant_id, as_of, args.tool, arguments), "fake"
    if args.tool == _CAPABILITY and not args.manufacturing_db:
        raise ValueError("SQLite adapter requires the manufacturing database.")
    if args.tool == _SENSORS and not args.equipment_db:
        raise ValueError("SQLite adapter requires the equipment database.")
    return (
        SQLiteProcessDiagnosticsAdapter(
            args.manufacturing_db if args.tool == _CAPABILITY else None,
            args.equipment_db if args.tool == _SENSORS else None,
            demo_tenant_id=args.source_tenant_id,
        ),
        "sqlite",
    )


def _application(
    *,
    args: argparse.Namespace,
    as_of: date,
    adapter: object,
    guard: ToolLoopGuard,
    context: RuntimeContext,
    model: object,
):
    definition = AgentDefinition(
        "diagnostics-demo",
        "1.0.0",
        "analyst",
        "Run approved process diagnostics.",
        (
            ComponentReference(_CAPABILITY, "1.0.0"),
            ComponentReference(_SENSORS, "1.0.0"),
        ),
        ComponentReference("diagnostics-demo-model", "1.0.0"),
        ComponentReference("diagnostics-demo-policy", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    application = assemble_agent(
        definition,
        model=model,
        events=_Events([]),
        bindings=(
            create_process_capability_binding(adapter, today=lambda: as_of),
            create_sensor_summary_binding(adapter, today=lambda: as_of),
        ),
        policy=DemoToolPolicy(
            _NATIVE_TOOLS, frozenset({"analyst"}), tenant_id=args.source_tenant_id
        ),
        budget_factory=lambda: LoopGuardToolBudget(guard),
        server_capabilities=_NATIVE_TOOLS,
        model_policy_ref=ComponentReference("diagnostics-demo-model", "1.0.0"),
        policy_ref=ComponentReference("diagnostics-demo-policy", "1.0.0"),
    )
    return application.new_run(context, result_policy=projector), projector


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        as_of = date.fromisoformat(args.as_of)
        arguments = json.loads(args.arguments)
        if (
            args.timeout_ms < 0
            or args.max_tool_calls < 0
            or not isinstance(arguments, dict)
        ):
            raise ValueError
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    try:
        adapter, adapter_kind = _adapter(args, as_of, arguments)
    except ValueError as exc:
        return {"error": str(exc)}
    plan = _plan(args.tool, arguments, args.max_tool_calls)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        f"diagnostics-{args.mode}-demo",
        ToolExecutionLimits(
            args.max_tool_calls, 100, time.monotonic() + args.timeout_ms / 1000
        ),
    )
    model: object = (
        _NeverSelectModel()
        if args.mode == "ready"
        else _TwoResponseModel(args.tool, json.dumps(arguments, ensure_ascii=False))
    )
    try:
        run, projector = _application(
            args=args,
            as_of=as_of,
            adapter=adapter,
            guard=guard,
            context=context,
            model=model,
        )
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    progress: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def notify(_progress: object, event: dict) -> None:
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
        model_calls = 0
        final_response: str | None = None
        tool_messages: list[dict[str, str]] = []
    else:
        first = await run.model_stage(
            call_id="diagnostics-model-1",
            messages=(ModelMessage("user", "Run fixed diagnostics step."),),
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
        tool_messages = list(outcome.tool_messages)
        second = await run.model_stage(
            call_id="diagnostics-model-2",
            messages=(
                ModelMessage("user", "Run fixed diagnostics step."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage(
                        "tool", item["content"], tool_call_id=item["tool_call_id"]
                    )
                    for item in tool_messages
                ),
            ),
        )
        final_response = classify_loop_response(second.value).content
        model_calls = len(model.requests)
    return {
        "mode": args.mode,
        "adapter_kind": adapter_kind,
        "plan": _safe_plan(plan),
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": _source_scopes(outcome.trace),
        "typed_results": [_typed_result(result) for result in outcome.tool_results],
        "tool_messages": tool_messages,
        "final_response": final_response,
        "guard": guard.summary(),
        "model_tool_selection_calls": 0 if args.mode == "ready" else 1,
        "model_response_calls": model_calls,
        "progress": progress,
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
    except Exception:  # noqa: BLE001 - standalone output remains sanitized
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
