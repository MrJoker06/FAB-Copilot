from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolStatus
from app.agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.integrations.manufacturing.sqlite_equipment_health import (
    SQLiteEquipmentHealthAdapter,
)
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthDataError,
    EquipmentHealthInputError,
    EquipmentHealthQuery,
    EquipmentHealthTimeoutError,
)
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "user"
    roles: tuple[str, ...] = ("analyst",)


def plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="equipment-health",
        schema_version="1",
        planner_version="test",
        status="ready",
        reason="",
        route_intent="equipment_health",
        playbook_id=None,
        playbook_version=None,
        scope_contract=AnalysisScopeContract("fab", (), (), ()),
        required_evidence_ids=(),
        steps=(),
        budget=PlanBudget(4, 4, 1, 10, {"get_equipment_health": 4}, 4, 2),
        missing_inputs=(),
        clarification_questions=(),
    )


class EquipmentHealthDispatchTests(unittest.TestCase):
    def dispatcher(self, port, today):
        registry = ToolRegistry()
        registry.register_native(create_equipment_health_binding(port, today=today))
        return ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}), tenant_id="demo"
            ),
            budget=LoopGuardToolBudget(ToolLoopGuard(plan())),
            allowed_tools=frozenset({"get_equipment_health"}),
        )

    def context(self):
        return ToolExecutionContext(Principal(), "run", "call", object())

    def test_prepare_freezes_dates_and_uses_equipment_scope(self):
        dates = iter((date(2026, 10, 24), date(2026, 10, 25)))
        requested = EquipmentHealthQuery(
            date(2026, 7, 27), date(2026, 10, 24), equipment_id="CMP-01"
        )
        port = FakeEquipmentHealthAdapter("demo", {requested: ()})
        result = asyncio.run(
            self.dispatcher(port, lambda: next(dates)).dispatch(
                "get_equipment_health",
                {"process_step": "etch", "equipment_id": "cmp-01"},
                self.context(),
            )
        )
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(port.calls, [requested])
        self.assertEqual(result.sources[0].scope.equipment_ids, ("CMP-01",))
        self.assertEqual(result.sources[0].scope.process_steps, ())

    def test_invalid_input_is_rejected_before_the_adapter_fetches(self):
        port = FakeEquipmentHealthAdapter("demo", {})
        result = asyncio.run(
            self.dispatcher(port, lambda: date(2026, 10, 24)).dispatch(
                "get_equipment_health",
                {"start": "2026-10-25", "end": "2026-10-24"},
                self.context(),
            )
        )
        self.assertEqual(result.status, ToolStatus.INVALID_ARGUMENTS)
        self.assertEqual(port.calls, [])

    def test_source_timeout_is_both_equipment_and_dispatch_timeout(self):
        self.assertIsInstance(EquipmentHealthInputError("x"), ToolInputError)
        error = EquipmentHealthTimeoutError("x")
        self.assertIsInstance(error, EquipmentHealthDataError)
        self.assertIsInstance(error, ToolDataSourceError)
        self.assertIsInstance(error, ToolSourceTimeout)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manufacturing, equipment = root / "m.db", root / "e.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
                )
            closed = []
            real_connect = sqlite3.connect

            class InterruptingConnection:
                def __init__(self, connection):
                    self.connection = connection
                    self.callback = None

                def execute(self, sql, parameters=()):
                    if "WITH run_stats" in sql:
                        self.callback()
                        raise sqlite3.OperationalError("interrupted")
                    return self.connection.execute(sql, parameters)

                def set_progress_handler(self, callback, count):
                    self.callback = callback
                    self.connection.set_progress_handler(callback, count)

                def close(self):
                    closed.append(True)
                    self.connection.close()

            def connect(*args, **kwargs):
                return InterruptingConnection(real_connect(*args, **kwargs))

            adapter = SQLiteEquipmentHealthAdapter(
                manufacturing, equipment, demo_tenant_id="demo", query_timeout_ms=1
            )
            with (
                patch(
                    "app.integrations.manufacturing.sqlite_equipment_health.sqlite3.connect",
                    connect,
                ),
                patch(
                    "app.integrations.manufacturing.sqlite_equipment_health.time.monotonic",
                    side_effect=(0.0, 1.0),
                ),
                self.assertRaises(EquipmentHealthTimeoutError),
            ):
                adapter.fetch(
                    EquipmentHealthQuery(date(2026, 1, 1), date(2026, 1, 1)),
                    Principal(),
                )
            self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
