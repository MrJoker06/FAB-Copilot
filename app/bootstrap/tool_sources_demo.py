"""Offline execution runner for the explicit tool-source composition."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
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
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import ToolExecutionLimits
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.demo_data.tool_sources.equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.tools.equipment_health.data_source import (
    SQLiteEquipmentHealthAdapter,
)
from ..integrations.manufacturing.sqlite_named_queries import SQLiteNamedQueryAdapter
from ..integrations.manufacturing.sqlite_operational_reports import (
    SQLiteOperationalReportsAdapter,
)
from app.tools.process_diagnostics.data_source import (
    SQLiteProcessDiagnosticsAdapter,
)
from ..integrations.manufacturing.sqlite_production_reports import (
    SQLiteProductionReportsAdapter,
)
from ..knowledge.search_tool.contracts import KnowledgeSearchInput
from ..manufacturing.enterprise_tools.contracts import EnterpriseWindow
from app.tools.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthQuery,
)
from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)
from . import (
    diagnostics_demo,
    enterprise_tools_demo,
    knowledge_search_demo,
    named_queries_demo,
    operational_reports_demo,
    production_reports_demo,
)
from .agent_assembly import assemble_agent
from .loop_assembly import bind_loop_run
from .ready_assembly import bind_ready_run
from .tool_sources import ToolSources, create_tool_bindings

AS_OF = date(2026, 10, 24)
LOT_TOOLS = frozenset(
    (
        "get_lot_identity",
        "get_lot_process_history",
        "get_lot_excursion_history",
        "get_lot_defect_history",
        "get_lot_wafer_map_patterns",
    )
)


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "tool-sources-demo"
    roles: tuple[str, ...] = ("analyst",)


@dataclass(slots=True)
class _ReadyModel:
    calls: int = 0

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        del request, context
        self.calls += 1
        raise AssertionError("Ready execution does not select tools through the model")


@dataclass(slots=True)
class _LoopModel:
    tool: str
    arguments: str
    calls: int = 0

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        del context
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(ModelToolCall("tool-sources-1", self.tool, self.arguments),)
            )
        expected = ModelToolCall("tool-sources-1", self.tool, self.arguments)
        user = next(
            (
                item
                for item in request.messages
                if item.role == "user"
                and item.content == "Run selected offline fixture tool."
            ),
            None,
        )
        assistant = next(
            (
                item
                for item in request.messages
                if item.role == "assistant" and item.tool_calls == (expected,)
            ),
            None,
        )
        tool_message = next(
            (
                item
                for item in request.messages
                if item.role == "tool" and item.tool_call_id == expected.call_id
            ),
            None,
        )
        if self.calls != 2 or user is None or assistant is None or tool_message is None:
            raise AssertionError("fixture Loop requires its tool message")
        try:
            payload = json.loads(tool_message.content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AssertionError("fixture Loop requires JSON tool data") from exc
        if (
            not isinstance(payload, dict)
            or "ok" not in payload
            or "data" not in payload
        ):
            raise AssertionError("fixture Loop received inconsistent tool data")
        return ModelResponse(content="Offline fixture Loop completed.")


def _arguments(tool: str) -> dict[str, object]:
    if tool in LOT_TOOLS:
        return {"lot_id": "LOT-001"}
    if tool == "search_knowledge":
        return {"query": "LITHO 颗粒"}
    if tool == "get_process_pass_rate":
        return {"process_step": "CMP", "equipment_id": "CMP-01"}
    if tool == "query_enterprise_data":
        return {"entity": "lots"}
    return {}


def _merge(factory: Any, names: tuple[str, ...], attribute: str) -> Any:
    first, merged = factory(names[0]), {}
    for name in names:
        merged.update(getattr(factory(name), attribute))
    setattr(first, attribute, merged)
    return first


def build_fake_sources(as_of: date) -> ToolSources:
    """Build synthetic ports only; this function never opens SQLite."""
    health_query = EquipmentHealthQuery(as_of - timedelta(days=89), as_of)
    health = FakeEquipmentHealthAdapter(
        "demo",
        {health_query: (EquipmentHealthAggregate("CMP-01", 5, 1, 0.1, 99.0, 0, 1.0),)},
    )
    diagnostics = _merge(
        lambda n: diagnostics_demo._fake_adapter("demo", as_of, n, {}),
        ("get_process_capability", "get_sensor_summary"),
        "snapshots",
    )
    production = _merge(
        lambda n: production_reports_demo._fake("demo", as_of, n, _arguments(n)),
        ("get_fab_overview", "get_yield_trend", "get_process_pass_rate"),
        "snapshots",
    )
    operational = _merge(
        lambda n: operational_reports_demo._fake("demo", as_of, n, {}),
        ("get_equipment_productivity", "get_defect_pareto", "get_recent_excursions"),
        "snapshots",
    )
    base = argparse.Namespace(
        adapter="fake", source_tenant_id="demo", tool="", arguments="{}"
    )
    enterprise = _merge(
        lambda n: enterprise_tools_demo._adapter(
            argparse.Namespace(**{**vars(base), "tool": n}),
            EnterpriseWindow(as_of),
            _arguments(n),
        )[0],
        (
            "get_enterprise_data_manifest",
            "get_enterprise_fab_summary",
            "query_enterprise_data",
        ),
        "snapshots",
    )
    named = _merge(
        lambda n: named_queries_demo._fake("demo", as_of, n, _arguments(n)),
        tuple(named_queries_demo._TOOLS),
        "fixtures",
    )
    knowledge_args = argparse.Namespace(
        adapter="fake",
        source_tenant_id="demo",
        source_user_id="tool-sources-demo",
        default_tenant_id="demo",
    )
    knowledge = knowledge_search_demo._adapter(
        knowledge_args,
        KnowledgeSearchInput.from_arguments(_arguments("search_knowledge")),
    )[0]
    return ToolSources(
        health, diagnostics, production, operational, enterprise, knowledge, named
    )


def build_local_sources(
    manufacturing_db: Path, equipment_db: Path, quality_db: Path, *, as_of: date = AS_OF
) -> ToolSources:
    """Build exactly 17 explicit SQLite bindings plus four fixture-backed ports."""
    if not all(path.is_file() for path in (manufacturing_db, equipment_db, quality_db)):
        raise ValueError(
            "local-fixture requires existing --manufacturing-db, --equipment-db, and --quality-db"
        )
    fake = build_fake_sources(as_of)
    provider = enterprise_tools_demo._FixtureProvider(
        "demo", fake.enterprise_data.snapshots
    )
    enterprise = enterprise_tools_demo.ProviderEnterpriseToolsAdapter(
        provider,
        demo_tenant_id="demo",
        expected_provider_id=enterprise_tools_demo._FixtureProvider.provider_id,
    )
    knowledge_args = argparse.Namespace(
        adapter="backend",
        source_tenant_id="demo",
        source_user_id="tool-sources-demo",
        default_tenant_id="demo",
    )
    knowledge = knowledge_search_demo._adapter(
        knowledge_args,
        KnowledgeSearchInput.from_arguments(_arguments("search_knowledge")),
    )[0]
    return ToolSources(
        SQLiteEquipmentHealthAdapter(
            manufacturing_db, equipment_db, demo_tenant_id="demo"
        ),
        SQLiteProcessDiagnosticsAdapter(
            manufacturing_db, equipment_db, demo_tenant_id="demo"
        ),
        SQLiteProductionReportsAdapter(manufacturing_db, demo_tenant_id="demo"),
        SQLiteOperationalReportsAdapter(
            equipment_path=equipment_db,
            quality_path=quality_db,
            manufacturing_path=manufacturing_db,
            demo_tenant_id="demo",
        ),
        enterprise,
        knowledge,
        SQLiteNamedQueryAdapter(
            manufacturing_path=manufacturing_db,
            equipment_path=equipment_db,
            quality_path=quality_db,
            demo_tenant_id="demo",
        ),
    )


def _plan(
    tool: str, arguments: dict[str, object], names: frozenset[str], budget: int
) -> ExecutionPlan:
    return ExecutionPlan(
        "tool-sources-demo",
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
                "Explicit source tool",
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
        PlanBudget(budget, budget, 2, 100, {name: budget for name in names}, 1, 1),
        (),
        (),
    )


async def run_tool_sources(
    sources: ToolSources,
    *,
    tool: str,
    mode: str,
    as_of: date = AS_OF,
    include_summary: bool = False,
    max_tool_calls: int = 1,
    arguments: dict[str, object] | None = None,
    principal: object | None = None,
) -> dict[str, object]:
    """Run a selected binding through native Ready or two-stage Loop dispatch."""
    bindings = create_tool_bindings(
        sources,
        as_of=as_of,
        default_tenant_id="demo",
        include_equipment_health_summary=include_summary,
    )
    names = frozenset(item.definition.name for item in bindings)
    if mode not in {"ready", "loop"} or (
        arguments is not None and not isinstance(arguments, dict)
    ):
        raise ValueError("invalid explicit runner input")
    argument_value = _arguments(tool) if arguments is None else arguments
    plan = _plan(tool, argument_value, names, max_tool_calls)
    guard = ToolLoopGuard(plan)
    principal_value = _Principal() if principal is None else principal
    context = RuntimeContext(
        principal_value,
        "tool-sources-demo",
        ToolExecutionLimits(max_tool_calls, 100, time.monotonic() + 2),
    )
    model: _ReadyModel | _LoopModel = (
        _ReadyModel()
        if mode == "ready"
        else _LoopModel(tool, json.dumps(argument_value, ensure_ascii=False))
    )
    definition = AgentDefinition(
        "tool-sources-demo",
        "1.0.0",
        "analyst",
        "offline explicit source demonstration",
        tuple(ComponentReference(n, "1.0.0") for n in sorted(names)),
        ComponentReference("fixture-model", "1.0.0"),
        ComponentReference("fixture-policy", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    app = assemble_agent(
        definition,
        model=model,
        events=named_queries_demo._Events([]),
        bindings=bindings,
        policy=DemoToolPolicy(
            names,
            frozenset({"analyst"}),
            tenant_id="demo",
        ),
        budget_factory=lambda: LoopGuardToolBudget(guard),
        server_capabilities=names,
        model_policy_ref=ComponentReference("fixture-model", "1.0.0"),
        policy_ref=ComponentReference("fixture-policy", "1.0.0"),
    )
    run = app.new_run(context, result_policy=projector)

    async def notify(_p: object, _event: dict[str, object]) -> None:
        return None

    def emit(_name: str, _run_id: str, **_details: object) -> None:
        return None

    if mode == "ready":
        outcome = await execute_dispatched_ready_plan(
            plan,
            guard,
            context.run_id,
            None,
            binding=bind_ready_run(plan, guard, run, projector),
            notify=notify,
            emit_event=emit,
        )
    else:
        first = await run.model_stage(
            call_id="tool-sources-model-1",
            messages=(ModelMessage("user", "Run selected offline fixture tool."),),
        )
        outcome = await execute_dispatched_loop_round(
            plan,
            guard,
            context.run_id,
            1,
            classify_loop_response(first.value),
            None,
            binding=bind_loop_run(plan, guard, run, projector),
            notify=notify,
            emit_event=emit,
        )
        second = await run.model_stage(
            call_id="tool-sources-model-2",
            messages=(
                ModelMessage("user", "Run selected offline fixture tool."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage(
                        "tool", item["content"], tool_call_id=item["tool_call_id"]
                    )
                    for item in outcome.tool_messages
                ),
            ),
        )
        if not classify_loop_response(second.value).content:
            raise RuntimeError("fixture Loop did not complete")
    result = outcome.tool_results[0]
    error = (
        None
        if result.error is None
        else {
            "code": result.error.code,
            "kind": result.error.kind.value,
            "public_message": result.error.public_message,
        }
    )
    return {
        "tool": result.tool_name,
        "status": result.status.value,
        "data": result.data,
        "row_count": result.row_count,
        "error": error,
        "sources": [
            {
                "source_ref": x.source_ref,
                "kind": x.source_kind.value,
                "grain": x.scope.grain,
                "scope": {
                    "tenant_id": x.scope.tenant_id,
                    "start": (
                        None
                        if x.scope.start_date is None
                        else x.scope.start_date.isoformat()
                    ),
                    "end": (
                        None
                        if x.scope.end_date is None
                        else x.scope.end_date.isoformat()
                    ),
                    "equipment_ids": list(x.scope.equipment_ids),
                    "process_steps": list(x.scope.process_steps),
                    "lot_ids": list(x.scope.lot_ids),
                    "grain": x.scope.grain,
                },
            }
            for x in result.sources
        ],
        "model_calls": model.calls,
        "guard_total_calls": guard.total_calls,
        "guard": guard.summary(),
        "model_tool_count": len(run.dispatcher.registry.model_tools),
        "tool_messages": list(getattr(outcome, "tool_messages", ())),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("fake", "local-fixture"), default="fake")
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--tool", default="get_equipment_health")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--as-of", default=AS_OF.isoformat())
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--equipment-db")
    parser.add_argument("--quality-db")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        as_of = date.fromisoformat(args.as_of)
        sources = (
            build_fake_sources(as_of)
            if args.profile == "fake"
            else build_local_sources(
                Path(args.manufacturing_db or ""),
                Path(args.equipment_db or ""),
                Path(args.quality_db or ""),
                as_of=as_of,
            )
        )
        payload = asyncio.run(
            run_tool_sources(
                sources,
                tool=args.tool,
                mode=args.mode,
                as_of=as_of,
                include_summary=args.summary,
            )
        )
        payload.update(profile=args.profile, company_connected=False)
    except Exception:  # noqa: BLE001 - CLI must never serialize raw dependency errors.
        payload = {"error": "invalid explicit offline demonstration request"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("status") == "succeeded" else 2


__all__ = ["build_fake_sources", "build_local_sources", "main", "run_tool_sources"]


if __name__ == "__main__":
    raise SystemExit(main())
