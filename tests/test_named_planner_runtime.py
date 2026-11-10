"""Generated named plans execute through native Ready and Loop bindings."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import unittest
from dataclasses import dataclass
from datetime import date

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.loop_response import classify_loop_response
from app.agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from app.agent_runtime.execution.runtime_contracts import (
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
)
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolSource,
    ToolSourceKind,
)
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import assemble_agent
from app.bootstrap.loop_assembly import bind_loop_run
from app.bootstrap.ready_assembly import bind_ready_run
from app.integrations.knowledge.fake_search import FakeKnowledgeSearchAdapter
from app.demo_data.tool_sources.named_queries import FakeNamedQueryAdapter
from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter
from app.intent_runtime.routing import route_question
from app.knowledge.search_tool.binding import create_knowledge_search_binding
from app.knowledge.search_tool.contracts import (
    KnowledgeSearchInput,
    KnowledgeSearchSnapshot,
    knowledge_scope,
)
from app.tools.named_queries.binding import create_named_query_bindings
from app.tools.named_queries.contracts import NamedQuery
from app.planning_runtime.named_planner import create_named_execution_plan
from tests import test_named_queries_adapters as adapter_tests


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("analyst",)


class _Events:
    async def emit(self, _event: object) -> None:
        return None


class _Model:
    async def complete(self, _request: object, _context: object) -> ModelResponse:
        return ModelResponse(content="unused")


def _fixture(query: NamedQuery) -> tuple[dict[str, object], ...]:
    lot = query.lot_id
    assert lot == "LOT-001"
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
    return (rows[query.kind],)


class NamedPlannerRuntimeTests(unittest.TestCase):
    def _plan_and_bindings(self):
        question = "追踪 LOT-001"
        plan = create_named_execution_plan(
            question, route_question(question, date(2026, 10, 31))
        )
        principal = _Principal()
        query_fixtures = {
            NamedQuery(kind, lot_id="LOT-001"): _fixture(
                NamedQuery(kind, lot_id="LOT-001")
            )
            for kind in (
                "lot_identity",
                "lot_process_history",
                "lot_excursions",
                "lot_defects",
                "lot_wafer_maps",
            )
        }
        named = FakeNamedQueryAdapter("demo", query_fixtures)
        search_arguments = next(
            step.parameters for step in plan.steps if step.tool == "search_knowledge"
        )
        search_query = KnowledgeSearchInput.from_arguments(search_arguments).resolve()
        snapshot = KnowledgeSearchSnapshot(
            search_query,
            "demo",
            "engineer",
            "engineer",
            {},
            (
                {
                    "source_type": "knowledge",
                    "reference_id": "KB-LOT-1",
                    "status": "Active",
                    "title": "Lot hold",
                    "section": "hold",
                    "process_steps": "CMP",
                    "authority": 5,
                    "tags": "lot",
                },
            ),
            (
                ToolSource(
                    "fake:knowledge",
                    "test",
                    ToolSourceKind.FAKE,
                    knowledge_scope(principal),
                ),
            ),
        )
        knowledge = FakeKnowledgeSearchAdapter(
            "demo", "engineer", {search_query: snapshot}
        )
        bindings = (
            *create_named_query_bindings(named, as_of=date(2026, 10, 31)),
            create_knowledge_search_binding(knowledge, default_tenant_id="demo"),
        )
        return plan, principal, bindings, named, knowledge

    def _run_ready(self):
        plan, principal, bindings, named, knowledge = self._plan_and_bindings()
        guard = ToolLoopGuard(plan)
        context = RuntimeContext(
            principal,
            "named-plan-ready",
            ToolExecutionLimits(20, 100, time.monotonic() + 5),
        )
        names = tuple(binding.definition.name for binding in bindings)
        app = assemble_agent(
            AgentDefinition(
                "named-plan",
                "1.0.0",
                "analyst",
                "Run named plan.",
                tuple(ComponentReference(name, "1.0.0") for name in names),
                ComponentReference("model", "1.0.0"),
                ComponentReference("policy", "1.0.0"),
            ),
            model=_Model(),
            events=_Events(),
            bindings=bindings,
            policy=DemoToolPolicy(
                frozenset(names), frozenset({"analyst"}), tenant_id="demo"
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset(names),
            model_policy_ref=ComponentReference("model", "1.0.0"),
            policy_ref=ComponentReference("policy", "1.0.0"),
        )
        projector = ReadyResultPolicy(
            knowledge_tools=frozenset({"search_knowledge"}),
            usable_knowledge_result=lambda _q, _r: True,
        )
        binding = bind_ready_run(
            plan, guard, app.new_run(context, result_policy=projector), projector
        )

        async def notify(_progress, _event):
            return None

        return (
            asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    guard,
                    context.run_id,
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            ),
            guard,
            named,
            knowledge,
        )

    def test_full_generated_lot_ready_plan_uses_native_fake_ports(self) -> None:
        outcome, guard, named, knowledge = self._run_ready()
        expected = create_named_execution_plan(
            "追踪 LOT-001", route_question("追踪 LOT-001", date(2026, 10, 31))
        )
        self.assertEqual(
            [item["tool"] for item in outcome.trace],
            [step.tool for step in expected.steps],
        )
        self.assertEqual(len(named.calls), 5)
        self.assertEqual(len(knowledge.calls), 1)
        self.assertEqual(guard.total_calls, 6)
        self.assertTrue(
            all(result.status.value == "succeeded" for result in outcome.tool_results)
        )
        self.assertEqual(outcome.tool_results[0].data[0]["lot_id"], "LOT-001")
        self.assertEqual(
            outcome.tool_results[0].sources[0].source_kind, ToolSourceKind.FAKE
        )

    def test_full_generated_lot_loop_plan_matches_tool_messages(self) -> None:
        plan, principal, bindings, named, knowledge = self._plan_and_bindings()
        guard = ToolLoopGuard(plan)
        context = RuntimeContext(
            principal,
            "named-plan-loop",
            ToolExecutionLimits(20, 100, time.monotonic() + 5),
        )
        names = tuple(binding.definition.name for binding in bindings)
        app = assemble_agent(
            AgentDefinition(
                "named-plan",
                "1.0.0",
                "analyst",
                "Run named plan.",
                tuple(ComponentReference(name, "1.0.0") for name in names),
                ComponentReference("model", "1.0.0"),
                ComponentReference("policy", "1.0.0"),
            ),
            model=_Model(),
            events=_Events(),
            bindings=bindings,
            policy=DemoToolPolicy(
                frozenset(names), frozenset({"analyst"}), tenant_id="demo"
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset(names),
            model_policy_ref=ComponentReference("model", "1.0.0"),
            policy_ref=ComponentReference("policy", "1.0.0"),
        )
        projector = ReadyResultPolicy(
            knowledge_tools=frozenset({"search_knowledge"}),
            usable_knowledge_result=lambda _q, _r: True,
        )
        binding = bind_loop_run(
            plan, guard, app.new_run(context, result_policy=projector), projector
        )
        response = classify_loop_response(
            ModelResponse(
                tool_calls=tuple(
                    ModelToolCall(str(index), step.tool, json.dumps(step.parameters))
                    for index, step in enumerate(plan.steps, 1)
                )
            )
        )

        async def notify(_progress, _event):
            return None

        outcome = asyncio.run(
            execute_dispatched_loop_round(
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
        )
        self.assertEqual(len(outcome.tool_messages), len(plan.steps))
        self.assertEqual(len(named.calls), 5)
        self.assertEqual(len(knowledge.calls), 1)
        self.assertTrue(
            all(
                json.loads(message["content"])["ok"]
                for message in outcome.tool_messages
            )
        )

    def test_full_generated_lot_ready_plan_uses_sqlite_port(self) -> None:
        fixture = adapter_tests.NamedQueryAdapterTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        for path, table in (
            (fixture.manufacturing, "lots"),
            (fixture.manufacturing, "process_runs"),
            (fixture.quality, "defect_records"),
            (fixture.quality, "wafer_maps"),
        ):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    f"UPDATE {table} SET lot_id = ? WHERE lot_id = ?", ("LOT-001", "L1")
                )
        plan, principal, _bindings, _named, knowledge = self._plan_and_bindings()
        adapter = SQLiteNamedQueryAdapter(
            manufacturing_path=fixture.manufacturing,
            equipment_path=fixture.equipment,
            quality_path=fixture.quality,
            demo_tenant_id="demo",
        )
        bindings = (
            *create_named_query_bindings(adapter, as_of=date(2026, 10, 31)),
            create_knowledge_search_binding(knowledge, default_tenant_id="demo"),
        )
        guard = ToolLoopGuard(plan)
        context = RuntimeContext(
            principal, "sqlite-plan", ToolExecutionLimits(20, 100, time.monotonic() + 5)
        )
        names = tuple(item.definition.name for item in bindings)
        app = assemble_agent(
            AgentDefinition(
                "named-plan",
                "1.0.0",
                "analyst",
                "Run named plan.",
                tuple(ComponentReference(name, "1.0.0") for name in names),
                ComponentReference("model", "1.0.0"),
                ComponentReference("policy", "1.0.0"),
            ),
            model=_Model(),
            events=_Events(),
            bindings=bindings,
            policy=DemoToolPolicy(
                frozenset(names), frozenset({"analyst"}), tenant_id="demo"
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset(names),
            model_policy_ref=ComponentReference("model", "1.0.0"),
            policy_ref=ComponentReference("policy", "1.0.0"),
        )
        projector = ReadyResultPolicy(
            knowledge_tools=frozenset({"search_knowledge"}),
            usable_knowledge_result=lambda _q, _row: True,
        )
        binding = bind_ready_run(
            plan, guard, app.new_run(context, result_policy=projector), projector
        )

        async def notify(_progress, _event):
            return None

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                context.run_id,
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_a, **_kw: None,
            )
        )
        self.assertEqual(guard.total_calls, 6)
        self.assertEqual(
            [result.sources[0].source_kind for result in outcome.tool_results[:5]],
            [ToolSourceKind.SQLITE] * 5,
        )
        self.assertEqual(outcome.tool_results[0].data[0]["lot_id"], "LOT-001")
        self.assertEqual(outcome.tool_results[1].data[0]["run_time"], "2020-01-01")


if __name__ == "__main__":
    unittest.main()
