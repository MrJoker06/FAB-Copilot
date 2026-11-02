"""Run fixed manufacturing named queries through Ready or Loop dispatch."""

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
from ..integrations.manufacturing.fake_named_queries import FakeNamedQueryAdapter
from ..integrations.manufacturing.sqlite_named_queries import SQLiteNamedQueryAdapter
from ..manufacturing.named_queries.binding import create_named_query_bindings
from ..manufacturing.named_queries.contracts import (
    TOOL_KINDS,
    EquipmentEventsInput,
    EquipmentExcursionsInput,
    LotQueryInput,
    NamedQuery,
    NamedQueryInputError,
    ProductYieldInput,
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

_TOOLS = tuple(TOOL_KINDS)
_INPUTS = {
    "product_yield": ProductYieldInput,
    "equipment_events": EquipmentEventsInput,
    "equipment_excursions": EquipmentExcursionsInput,
    **{
        x: LotQueryInput
        for x in (
            "lot_identity",
            "lot_process_history",
            "lot_excursions",
            "lot_defects",
            "lot_wafer_maps",
        )
    },
}


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
                tool_calls=(ModelToolCall("named-query-1", self.tool, self.arguments),)
            )
        if len(self.requests) != 2:
            raise AssertionError("unexpected named-query Loop sequence")
        messages = [
            m
            for m in request.messages
            if m.role == "tool" and m.tool_call_id == "named-query-1"
        ]
        if len(messages) != 1:
            raise AssertionError("named-query Loop fixture requires its tool message")
        try:
            payload = json.loads(messages[0].content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AssertionError(
                "named-query Loop fixture requires JSON tool data"
            ) from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("ok"), bool)
            or "data" not in payload
            or not isinstance(payload.get("execution_state"), str)
        ):
            raise AssertionError(
                "named-query Loop fixture received inconsistent tool data"
            )
        return ModelResponse(content="Fixed named-query Loop fixture completed.")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("ready", "loop"), default="ready")
    p.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    p.add_argument("--manufacturing-db")
    p.add_argument("--equipment-db")
    p.add_argument("--quality-db")
    p.add_argument("--source-tenant", default="demo")
    p.add_argument("--tenant", default="demo")
    p.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    p.add_argument("--tool", default="get_product_yield_breakdown")
    p.add_argument("--arguments", default="{}")
    p.add_argument("--as-of", default="2026-10-30")
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--max-tool-calls", type=int, default=1)
    return p


def _query(tool: str, args: dict[str, object], as_of: date) -> NamedQuery:
    kind = TOOL_KINDS[tool]
    return _INPUTS[kind].from_arguments(args).resolve(kind, as_of)


def _fixture(q: NamedQuery) -> tuple[dict[str, object], ...]:
    if q.kind == "product_yield":
        return (
            {
                "product": q.product or "Logic-A",
                "technology_nm": 7,
                "lots": 2,
                "wafers": 50,
                "yield_pct": 96.0,
            },
        )
    if q.kind == "equipment_events":
        return (
            {
                "equipment_id": q.equipment_id or "CMP-01",
                "event_time": q.end.isoformat(),
                "event_type": "maintenance",
                "duration_minutes": 15.0,
                "severity": "low",
                "reason": "scheduled",
            },
        )
    if q.kind == "equipment_excursions":
        return (
            {
                "lot_id": "LOT-001",
                "run_time": q.end.isoformat(),
                "process_step": q.process_step or "CMP",
                "equipment_id": q.equipment_id or "CMP-01",
                "excursion_code": "E001",
                "measurement_name": "thickness",
                "measurement_value": 10.0,
                "measurement_unit": "nm",
                "spec_lsl": 9.0,
                "spec_usl": 11.0,
            },
        )
    lot = q.lot_id or "LOT-001"
    rows = {
        "lot_identity": {
            "lot_id": lot,
            "product": "Logic-A",
            "technology_nm": 7,
            "route": "logic",
            "priority": "normal",
            "start_time": "2020-01-01",
            "complete_time": None,
            "status": "active",
            "wafer_count": 25,
            "good_wafers": 24,
            "yield_rate": 0.96,
            "cycle_time_hours": 10.0,
            "hold_hours": 0.0,
        },
        "lot_process_history": {
            "lot_id": lot,
            "operation_seq": 1,
            "layer_name": "M1",
            "process_step": "CMP",
            "equipment_id": "CMP-01",
            "chamber": "A",
            "recipe": "R1",
            "run_time": "2020-01-02",
            "queue_hours": 1.0,
            "rework_flag": 0,
        },
        "lot_excursions": {
            "lot_id": lot,
            "operation_seq": 1,
            "run_time": "2020-01-02",
            "process_step": "CMP",
            "equipment_id": "CMP-01",
            "excursion_code": "E001",
            "measurement_name": "thickness",
            "measurement_value": 8.0,
            "measurement_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 11.0,
        },
        "lot_defects": {
            "lot_id": lot,
            "detected_time": "2020-01-03",
            "process_step": "CMP",
            "defect_type": "Particle",
            "count": 2,
            "disposition": "review",
        },
        "lot_wafer_maps": {
            "lot_id": lot,
            "wafer_no": 1,
            "detected_time": "2020-01-04",
            "process_step": "CMP",
            "equipment_id": "CMP-01",
            "pattern_class": "edge",
            "tested_dies": 100,
            "failed_dies": 2,
        },
    }
    return (rows[q.kind],)


def _fake(
    tenant: str, as_of: date, tool: str, args: dict[str, object]
) -> FakeNamedQueryAdapter:
    try:
        q = _query(tool, args, as_of)
    except (KeyError, NamedQueryInputError):
        return FakeNamedQueryAdapter(tenant, {})
    return FakeNamedQueryAdapter(tenant, {q: _fixture(q)})


def _plan(tool: str, args: dict[str, object], calls: int) -> ExecutionPlan:
    return ExecutionPlan(
        "named-queries-demo",
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
                "Named manufacturing query",
                tool,
                args,
                {},
                (),
                (),
                True,
                (),
                100,
                "primary",
            ),
        ),
        PlanBudget(calls, calls, 2, 100, {x: calls for x in _TOOLS}, 1, 1),
        (),
        (),
    )


def _typed(x: Any) -> dict[str, object]:
    return {
        "call_id": x.call_id,
        "tool": x.tool_name,
        "version": x.tool_version,
        "status": x.status.value,
        "state": x.execution_state.value,
        "execution_state": x.execution_state.value,
        "row_count": x.row_count,
        "data": x.data,
        "error": None
        if x.error is None
        else {
            "code": x.error.code,
            "kind": x.error.kind.value,
            "public_message": x.error.public_message,
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
            raise ValueError
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    adapter = (
        SQLiteNamedQueryAdapter(
            manufacturing_path=args.manufacturing_db,
            equipment_path=args.equipment_db,
            quality_path=args.quality_db,
            demo_tenant_id=args.source_tenant,
        )
        if args.adapter == "sqlite"
        else _fake(args.source_tenant, as_of, args.tool, arguments)
    )
    plan = _plan(args.tool, arguments, args.max_tool_calls)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant, "demo-user", (args.role,)),
        f"named-{args.mode}-demo",
        ToolExecutionLimits(
            args.max_tool_calls, 100, time.monotonic() + args.timeout_ms / 1000
        ),
    )
    model = (
        _ReadyModel()
        if args.mode == "ready"
        else _LoopModel(args.tool, json.dumps(arguments, ensure_ascii=False))
    )
    try:
        definition = AgentDefinition(
            "named-queries-demo",
            "1.0.0",
            "analyst",
            "Run approved named manufacturing queries.",
            tuple(ComponentReference(x, "1.0.0") for x in _TOOLS),
            ComponentReference("named-queries-demo-model", "1.0.0"),
            ComponentReference("named-queries-demo-policy", "1.0.0"),
        )
        projector = ReadyResultPolicy()
        app = assemble_agent(
            definition,
            model=model,
            events=_Events([]),
            bindings=create_named_query_bindings(adapter, as_of=as_of),
            policy=DemoToolPolicy(
                frozenset(_TOOLS), frozenset({"analyst"}), tenant_id=args.source_tenant
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset(_TOOLS),
            model_policy_ref=ComponentReference("named-queries-demo-model", "1.0.0"),
            policy_ref=ComponentReference("named-queries-demo-policy", "1.0.0"),
        )
        run = app.new_run(context, result_policy=projector)
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    progress = []
    events = []

    async def notify(_p: object, event: dict[str, object]) -> None:
        progress.append({k: v for k, v in event.items() if k != "arguments"})

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
        messages = []
        final = None
    else:
        first = await run.model_stage(
            call_id="named-model-1",
            messages=(ModelMessage("user", "Run fixed named query."),),
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
            call_id="named-model-2",
            messages=(
                ModelMessage("user", "Run fixed named query."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage("tool", i["content"], tool_call_id=i["tool_call_id"])
                    for i in messages
                ),
            ),
        )
        final = classify_loop_response(second.value).content
    sources = {s["source_ref"]: s for x in outcome.trace for s in x.get("sources", ())}
    return {
        "mode": args.mode,
        "adapter_kind": args.adapter,
        "plan": {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "steps": [
                {"step_id": x.step_id, "tool": x.tool, "depends_on": list(x.depends_on)}
                for x in plan.steps
            ],
            "budget": {
                "max_tool_calls": plan.budget.max_tool_calls,
                "max_rows_per_call": plan.budget.max_rows_per_call,
                "per_tool_limits": dict(plan.budget.per_tool_limits),
            },
        },
        "typed_results": [_typed(x) for x in outcome.tool_results],
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
