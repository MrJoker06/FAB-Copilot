"""Run explicitly fake enterprise-data tools through Ready or Loop dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from copy import deepcopy
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
from app.demo_data.tool_sources.enterprise_data import (
    FakeEnterpriseToolsAdapter,
)
from app.tools.enterprise_data.data_source import (
    ProviderEnterpriseToolsAdapter,
)
from app.tools.enterprise_data.binding import (
    create_enterprise_manifest_binding,
    create_enterprise_sample_binding,
    create_enterprise_summary_binding,
)
from app.tools.enterprise_data.contracts import (
    EnterpriseDataError,
    EnterpriseInputError,
    EnterpriseManifestInput,
    EnterpriseQuery,
    EnterpriseSampleInput,
    EnterpriseSummaryInput,
    EnterpriseWindow,
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

_TOOLS = (
    "get_enterprise_data_manifest",
    "get_enterprise_fab_summary",
    "query_enterprise_data",
)
_PROVIDER = "fake-enterprise-v1"


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
        raise AssertionError("Ready execution must not select tools through the model")


@dataclass(slots=True)
class _LoopModel:
    tool: str
    arguments: str
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall("enterprise-tool-1", self.tool, self.arguments),
                )
            )
        if len(self.requests) == 2:
            messages = [
                m
                for m in request.messages
                if m.role == "tool" and m.tool_call_id == "enterprise-tool-1"
            ]
            if len(messages) != 1:
                raise AssertionError(
                    "enterprise Loop fixture requires its tool message"
                )
            try:
                payload = json.loads(messages[0].content)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AssertionError(
                    "enterprise Loop fixture requires JSON tool data"
                ) from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("ok"), bool)
                or "data" not in payload
                or not isinstance(payload.get("execution_state"), str)
            ):
                raise AssertionError(
                    "enterprise Loop fixture received inconsistent tool data"
                )
            return ModelResponse(
                content="Fixed enterprise data Loop fixture completed."
            )
        raise AssertionError("unexpected enterprise Loop sequence")


class _FixtureProvider:
    """Small in-memory Protocol implementation; it is deliberately not a real provider."""

    provider_id = _PROVIDER

    def __init__(
        self, tenant: str, snapshots: dict[EnterpriseQuery, dict[str, object]]
    ) -> None:
        self.tenant, self.snapshots, self.calls = tenant, deepcopy(snapshots), []

    def _data(self, query: EnterpriseQuery, principal: Any) -> dict:
        if principal.tenant_id != self.tenant:
            raise EnterpriseDataError("fixture tenant mismatch")
        self.calls.append(query)
        return deepcopy(self.snapshots[query])

    def manifest(self, principal: Any) -> dict:
        return self._data(
            EnterpriseQuery("manifest", as_of=next(iter(self.snapshots)).as_of),
            principal,
        )

    def summary(self, principal: Any, filters: dict) -> dict:
        query = next(
            q
            for q in self.snapshots
            if q.kind == "summary"
            and {"start": None, "end": None, "process_step": None, "equipment_id": None}
            | q.filter_dict()
            == filters
        )
        return self._data(query, principal)

    def page(
        self, entity: str, principal: Any, limit: int, cursor: str | None, filters: dict
    ) -> dict:
        if cursor is not None:
            raise EnterpriseDataError("fixture paging is illustrative only")
        query = next(
            q
            for q in self.snapshots
            if q.kind == "sample"
            and q.entity == entity
            and q.limit == limit
            and q.filter_dict() == filters
        )
        return self._data(query, principal)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--adapter", choices=("fake", "provider"), default="fake")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default=_TOOLS[0])
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of", default="2026-10-24")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


def _input(tool: str):
    return {
        "get_enterprise_data_manifest": EnterpriseManifestInput,
        "get_enterprise_fab_summary": EnterpriseSummaryInput,
        "query_enterprise_data": EnterpriseSampleInput,
    }.get(tool)


def _fixture(query: EnterpriseQuery, tenant: str) -> dict[str, object]:
    if query.kind == "manifest":
        return {
            "provider": _PROVIDER,
            "simulated": True,
            "tenant_id": tenant,
            "virtual_scale": {"lots": 1, "process-runs": 18, "sensor-events": 144},
            "entities": {
                "lots": {"path": "/api/enterprise/data/lots", "primary_key": "lot_id"},
                "process-runs": {
                    "path": "/api/enterprise/data/process-runs",
                    "primary_key": "run_id",
                },
                "sensor-events": {
                    "path": "/api/enterprise/data/sensor-events",
                    "primary_key": "reading_id",
                },
            },
            "analytics": {
                "summary_path": "/api/enterprise/data/summary",
                "semantics": "deterministic_projection",
                "supports": ["date_range", "process_step", "equipment_id"],
            },
            "pagination": {
                "strategy": "opaque_fixture_cursor",
                "default_limit": 100,
                "max_limit": 500,
            },
            "retention_days": 730,
            "partition_recommendation": ["tenant_id", "event_date", "process_step"],
            "data_classification": "synthetic_non_production",
        }
    if query.kind == "summary":
        return {
            "provider": _PROVIDER,
            "simulated": True,
            "tenant_id": tenant,
            "query": {
                "filters": query.filter_dict(),
                "effective_start": query.effective_start.isoformat(),
                "effective_end": query.effective_end.isoformat(),
                "query_id": "fake-aggregate-001",
            },
            "aggregation": {
                "semantics": "deterministic_projection",
                "exact": False,
                "description": "Explicit fake deterministic projection; not a company observation.",
            },
            "totals": {
                "lots": 1,
                "completed_lots": 1,
                "wafers": 25,
                "process_runs": 18,
                "sensor_events": 144,
            },
            "kpis": {
                "yield_pct": 95.0,
                "process_pass_rate_pct": 96.0,
                "avg_cycle_hours": 10.0,
                "hold_rate_pct": 1.0,
                "excursion_rate_pct": 0.5,
                "excursion_runs": 0,
                "sensor_missing_pct": 0.1,
                "sensor_outlier_pct": 0.2,
            },
            "equipment": [
                {
                    "equipment_id": query.filter_dict().get("equipment_id", "CMP-01"),
                    "projected_runs": 18,
                    "pass_rate_pct": 96.0,
                    "excursion_rate_pct": 0.5,
                    "health_score": 99.0,
                    "risk": "stable",
                }
            ],
            "lineage": {
                "source": _PROVIDER,
                "classification": "synthetic_non_production",
                "generated_from": [
                    "tenant_id",
                    "date_window",
                    "process_step",
                    "equipment_id",
                    "fixture",
                ],
                "as_of": query.as_of.isoformat() + "T00:00:00+00:00",
                "freshness": "deterministic_daily_snapshot",
            },
        }
    filters = query.filter_dict()
    stamp = query.effective_end.isoformat() + "T00:00:00+00:00"
    if query.entity == "lots":
        record = {
            "tenant_id": tenant,
            "lot_id": "DEMO-L000000000001",
            "product": filters.get("product", "Nova-P1"),
            "technology_nm": 28,
            "route": "LOGIC-18",
            "priority": "Normal",
            "start_time": stamp,
            "status": filters.get("status", "Completed"),
            "wafer_count": 25,
            "good_wafers": 24,
            "yield_rate": 0.96,
            "cycle_time_hours": 72.0,
            "synthetic": True,
        }
    elif query.entity == "process-runs":
        record = {
            "tenant_id": tenant,
            "run_id": "RUN-000000000000001",
            "lot_id": "DEMO-L000000000001",
            "operation_seq": 1,
            "process_step": filters.get("process_step", "CMP"),
            "equipment_id": filters.get("equipment_id", "CMP-01"),
            "chamber": "CH-1",
            "recipe": "CMP-R01",
            "run_time": stamp,
            "measurement_name": "Normalized process metric",
            "measurement_value": 100.0,
            "measurement_unit": "a.u.",
            "pass_flag": 1,
            "synthetic": True,
        }
    else:
        record = {
            "tenant_id": tenant,
            "reading_id": "SNS-0000000000000001",
            "lot_id": "DEMO-L000000000001",
            "process_step": filters.get("process_step", "CMP"),
            "equipment_id": filters.get("equipment_id", "CMP-01"),
            "chamber": "CH-1",
            "sample_time": stamp,
            "signal_name": filters.get("signal_name", "RF power"),
            "signal_value": 900.0,
            "signal_unit": "W",
            "is_missing": 0,
            "is_outlier": 0,
            "synthetic": True,
        }
    return {
        "provider": _PROVIDER,
        "simulated": True,
        "tenant_id": tenant,
        "entity": query.entity,
        "filters": filters,
        "records": [record],
        "page": {
            "count": 1,
            "limit": query.limit,
            "position": 0,
            "estimated_total": 3,
            "next_cursor": "illustrative-opaque-next",
        },
    }


def _adapter(
    args: argparse.Namespace, window: EnterpriseWindow, arguments: dict[str, object]
):
    model = _input(args.tool)
    try:
        query = model.from_arguments(arguments).resolve(window) if model else None
    except EnterpriseInputError:
        query = None
    snapshots = {query: _fixture(query, args.source_tenant_id)} if query else {}
    if args.adapter == "fake":
        return FakeEnterpriseToolsAdapter(args.source_tenant_id, snapshots), "fake"
    provider = _FixtureProvider(args.source_tenant_id, snapshots)
    return ProviderEnterpriseToolsAdapter(
        provider, demo_tenant_id=args.source_tenant_id, expected_provider_id=_PROVIDER
    ), "provider"


def _plan(tool: str, arguments: dict[str, object], maximum: int) -> ExecutionPlan:
    return ExecutionPlan(
        "enterprise-tools-demo",
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
                "Enterprise data",
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
        PlanBudget(maximum, maximum, 2, 100, {name: maximum for name in _TOOLS}, 1, 1),
        (),
        (),
    )


def _application(args, window, adapter, guard, context, model):
    definition = AgentDefinition(
        "enterprise-tools-demo",
        "1.0.0",
        "analyst",
        "Run approved fake enterprise data.",
        tuple(ComponentReference(n, "1.0.0") for n in _TOOLS),
        ComponentReference("enterprise-tools-demo-model", "1.0.0"),
        ComponentReference("enterprise-tools-demo-policy", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    application = assemble_agent(
        definition,
        model=model,
        events=_Events([]),
        bindings=(
            create_enterprise_manifest_binding(adapter, window=window),
            create_enterprise_summary_binding(adapter, window=window),
            create_enterprise_sample_binding(adapter, window=window),
        ),
        policy=DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id=args.source_tenant_id
        ),
        budget_factory=lambda: LoopGuardToolBudget(guard),
        server_capabilities=frozenset(_TOOLS),
        model_policy_ref=ComponentReference("enterprise-tools-demo-model", "1.0.0"),
        policy_ref=ComponentReference("enterprise-tools-demo-policy", "1.0.0"),
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
    """Expose only operator-reviewable plan metadata in the standalone demo."""

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


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        window = EnterpriseWindow(date.fromisoformat(args.as_of))
        arguments = json.loads(args.arguments)
        if (
            not isinstance(arguments, dict)
            or args.timeout_ms < 0
            or args.max_tool_calls < 0
        ):
            raise ValueError
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    adapter, adapter_kind = _adapter(args, window, arguments)
    plan = _plan(args.tool, arguments, args.max_tool_calls)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        f"enterprise-{args.mode}-demo",
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
        run, projector = _application(args, window, adapter, guard, context, model)
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    progress = []
    events = []

    async def notify(_progress, event):
        progress.append(
            {key: value for key, value in event.items() if key != "arguments"}
        )

    def emit_event(name, run_id, **details):
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
            call_id="enterprise-model-1",
            messages=(ModelMessage("user", "Run fixed enterprise data."),),
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
            call_id="enterprise-model-2",
            messages=(
                ModelMessage("user", "Run fixed enterprise data."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage("tool", m["content"], tool_call_id=m["tool_call_id"])
                    for m in messages
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
        "plan": _safe_plan(plan),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        payload = asyncio.run(_run(_parser().parse_args(argv)))
    except Exception:  # noqa: BLE001 - the standalone demo must emit safe JSON
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
