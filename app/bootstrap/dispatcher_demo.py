"""Standalone, deliberately small dispatcher demonstration (no application assembly)."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.execution.tool_result_bridge import project_tool_result
from ..agent_runtime.tools.contracts import ToolExecutionContext, ToolExecutionLimits
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from ..agent_runtime.tools.dispatcher import ToolDispatcher
from ..agent_runtime.tools.tool_registry import ToolRegistry
from ..integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from ..manufacturing.equipment_health.binding import create_equipment_health_binding
from ..manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthInput,
    EquipmentHealthInputError,
)
from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


def _plan(calls: int) -> ExecutionPlan:
    return ExecutionPlan(
        "dispatcher-demo",
        "1",
        "demo",
        "ready",
        "",
        "",
        None,
        None,
        AnalysisScopeContract("equipment", (), (), ()),
        (),
        (),
        PlanBudget(calls, calls, 1, 100, {"get_equipment_health": calls}, 1, 1),
        (),
        (),
    )


def _fake(
    tenant: str, as_of: date, arguments: dict[str, object]
) -> FakeEquipmentHealthAdapter:
    try:
        query = EquipmentHealthInput.from_arguments(arguments).resolve(as_of)
        fixtures = {
            query: (EquipmentHealthAggregate("DEMO-01", 12, 1, 0.123, 98.5, 2, 15.0),)
        }
    except EquipmentHealthInputError:
        fixtures = {}
    if fixtures and query.equipment_id:
        fixtures = {
            query: (
                EquipmentHealthAggregate(
                    query.equipment_id, 12, 1, 0.123, 98.5, 2, 15.0
                ),
            )
        }
    return FakeEquipmentHealthAdapter(tenant, fixtures)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--equipment-db")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default="get_equipment_health")
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of", default="2026-10-24")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        as_of = date.fromisoformat(args.as_of)
        if args.timeout_ms < 0 or args.max_tool_calls < 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"error": "Invalid operator arguments."}
    try:
        arguments = json.loads(args.arguments)
    except (TypeError, ValueError, RecursionError):
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    if args.adapter == "sqlite" and (
        not args.manufacturing_db or not args.equipment_db
    ):
        return {"error": "SQLite adapter requires both database paths."}
    if args.adapter == "sqlite":
        from ..integrations.manufacturing.sqlite_equipment_health import (
            SQLiteEquipmentHealthAdapter,
        )

        adapter = SQLiteEquipmentHealthAdapter(
            args.manufacturing_db,
            args.equipment_db,
            demo_tenant_id=args.source_tenant_id,
        )
    else:
        adapter = _fake(args.source_tenant_id, as_of, arguments)
    registry = ToolRegistry()
    registry.register_native(
        create_equipment_health_binding(adapter, today=lambda: as_of)
    )
    guard = ToolLoopGuard(_plan(args.max_tool_calls))
    dispatcher = ToolDispatcher(
        run_id="dispatcher-demo",
        registry=registry,
        policy=DemoToolPolicy(
            frozenset({"get_equipment_health"}),
            frozenset({"analyst"}),
            tenant_id=args.source_tenant_id,
        ),
        budget=LoopGuardToolBudget(guard),
        allowed_tools=frozenset({"get_equipment_health"}),
    )
    deadline = time.monotonic() + args.timeout_ms / 1000
    context = ToolExecutionContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        "dispatcher-demo",
        "demo-call",
        None,
        step_id="demo-step",
        limits=ToolExecutionLimits(args.max_tool_calls, 100, deadline),
    )
    result = await dispatcher.dispatch(args.tool, args.arguments, context)
    projection = project_tool_result(
        result, arguments=arguments, step_id=context.step_id
    )
    return {
        "result": {
            "call_id": result.call_id,
            "tool": result.tool_name,
            "version": result.tool_version,
            "status": result.status.value,
            "execution_state": result.execution_state.value,
            "row_count": result.row_count,
            "elapsed_ms": result.elapsed_ms,
            "error": (
                {
                    "code": result.error.code,
                    "public_message": result.error.public_message,
                    "kind": result.error.kind.value,
                }
                if result.error
                else None
            ),
            "sources": list(projection.sources),
            "data": result.data,
        },
        "projection": {
            "observation": projection.observation,
            "trace": projection.trace,
            "event": projection.event,
        },
        "guard": guard.summary(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
    except Exception:  # noqa: BLE001 - the standalone operator output is always sanitized
        payload = {"error": "INTERNAL_ERROR"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    return (
        0
        if "error" not in payload and payload["result"]["status"] == "succeeded"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
