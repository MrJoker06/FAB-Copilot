from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError, dataclass, fields, is_dataclass, replace
from datetime import date
from pathlib import Path

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeContractError,
)
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolStatus,
)
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.integrations.manufacturing.fake_equipment_health import demo_fake_adapter
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "agent-test"
    roles: tuple[str, ...] = ("analyst",)


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0
        self.request = None

    async def complete(self, request, context):
        self.calls += 1
        self.request = request
        return ModelResponse(
            tool_calls=(ModelToolCall("provider-call", "get_equipment_health", "{}"),)
        )


class FakeSink:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)
        if self.failure:
            raise self.failure


def _plan(calls: int = 1) -> ExecutionPlan:
    return ExecutionPlan(
        "agent-assembly",
        "1",
        "test",
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


def _definition(**changes) -> AgentDefinition:
    values = {
        "agent_id": "equipment-analyst",
        "version": "1.0.0",
        "role": "analyst",
        "instructions": "Use only the declared health tool.",
        "tools": (ComponentReference("get_equipment_health", "1.0.0"),),
        "model_policy": ComponentReference("demo-model", "1.0.0"),
        "default_policy": ComponentReference("demo-policy", "1.0.0"),
    }
    values.update(changes)
    return AgentDefinition(**values)


def _context(run_id: str = "run") -> RuntimeContext:
    return RuntimeContext(
        Principal(), run_id, ToolExecutionLimits(remaining_calls=1, max_result_rows=5)
    )


class AgentDefinitionTests(unittest.TestCase):
    def test_definition_is_frozen_explicit_and_has_no_runtime_or_identity_state(self):
        definition = _definition()
        self.assertTrue(is_dataclass(definition))
        self.assertTrue(type(definition).__dataclass_params__.frozen)
        self.assertIsInstance(definition.tools, tuple)
        self.assertEqual(definition.allowed_tools, frozenset({"get_equipment_health"}))
        self.assertEqual(
            {field.name for field in fields(definition)}
            - {
                "agent_id",
                "version",
                "role",
                "instructions",
                "tools",
                "model_policy",
                "default_policy",
                "skill_refs",
                "schema_version",
                "runtime_contract_version",
                "tool_contract_version",
            },
            set(),
        )
        with self.assertRaises(FrozenInstanceError):
            definition.role = "viewer"  # type: ignore[misc]
        for bad in (
            lambda: ComponentReference("tool", "1"),
            lambda: ComponentReference("*", "1.0.0"),
            lambda: _definition(
                tools=(
                    ComponentReference("a", "1.0.0"),
                    ComponentReference("a", "2.0.0"),
                )
            ),
            lambda: _definition(runtime_contract_version="2.0.0"),
            lambda: _definition(tool_contract_version="2.0.0"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bad()


class AgentAssemblyTests(unittest.IsolatedAsyncioTestCase):
    def binding(self):
        return create_equipment_health_binding(
            demo_fake_adapter(demo_tenant_id="demo", as_of=date(2026, 10, 24)),
            today=lambda: date(2026, 10, 24),
        )

    def factory(self, calls: int = 1):
        created = []

        def make_budget():
            budget = LoopGuardToolBudget(ToolLoopGuard(_plan(calls)))
            created.append(budget)
            return budget

        return make_budget, created

    def assemble(
        self,
        *,
        model=None,
        events=None,
        capabilities=frozenset({"get_equipment_health"}),
        calls=1,
    ):
        factory, created = self.factory(calls)
        app = assemble_agent(
            _definition(),
            model=model or FakeModel(),
            events=events or FakeSink(),
            bindings=(self.binding(),),
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}), frozenset({"analyst"}), "demo"
            ),
            budget_factory=factory,
            server_capabilities=capabilities,
            model_policy_ref=ComponentReference("demo-model", "1.0.0"),
            policy_ref=ComponentReference("demo-policy", "1.0.0"),
        )
        return app, created

    def test_invalid_assembly_rejects_before_budget_factory_and_requires_async_ports(
        self,
    ):
        class SyncModel:
            def complete(self, request, context):
                return ModelResponse()

        class SyncSink:
            def emit(self, event):
                return None

        class BadDecisionPolicy:
            def authorize(self, principal, name, scope):
                return object()

        class AsyncPolicy:
            async def authorize(self, principal, name, scope):
                return object()

        async def async_factory():
            return LoopGuardToolBudget(ToolLoopGuard(_plan()))

        class BadSchemaInput:
            @classmethod
            def from_arguments(cls, arguments):
                return cls()

            @classmethod
            def json_schema(cls):
                return {"not_json": object()}

        factory, created = self.factory()
        common = {
            "definition": _definition(),
            "model": FakeModel(),
            "events": FakeSink(),
            "bindings": (self.binding(),),
            "policy": DemoToolPolicy(frozenset({"get_equipment_health"})),
            "budget_factory": factory,
            "server_capabilities": frozenset({"get_equipment_health"}),
            "model_policy_ref": ComponentReference("demo-model", "1.0.0"),
            "policy_ref": ComponentReference("demo-policy", "1.0.0"),
        }
        cases = (
            {"model": None},
            {"events": None},
            {"policy": None},
            {"budget_factory": None},
            {"model": SyncModel()},
            {"events": SyncSink()},
            {"policy": AsyncPolicy()},
            {"budget_factory": async_factory},
            {"bindings": ()},
            {"bindings": (self.binding(), self.binding())},
            {
                "bindings": (
                    replace(
                        self.binding(),
                        definition=replace(self.binding().definition, version="2.0.0"),
                    ),
                )
            },
            {
                "bindings": (
                    replace(
                        self.binding(),
                        definition=replace(self.binding().definition, read_only=False),
                    ),
                )
            },
            {
                "bindings": (
                    replace(
                        self.binding(),
                        definition=replace(
                            self.binding().definition, input_model=BadSchemaInput
                        ),
                    ),
                )
            },
            {
                "definition": _definition(
                    skill_refs=(ComponentReference("skill", "1.0.0"),)
                )
            },
            {"server_capabilities": frozenset({"*"})},
            {"model_policy_ref": ComponentReference("other", "1.0.0")},
            {"policy_ref": ComponentReference("other", "1.0.0")},
        )
        for change in cases:
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(AssemblyError, "Agent assembly is invalid"),
            ):
                assemble_agent(**(common | change))
        self.assertEqual(created, [])

    async def test_bad_policy_decision_fails_without_budget_or_adapter_claim(self):
        class BadDecisionPolicy:
            def authorize(self, principal, name, scope):
                return object()

        adapter = demo_fake_adapter(demo_tenant_id="demo", as_of=date(2026, 10, 24))
        factory, created = self.factory()
        application = assemble_agent(
            _definition(),
            model=FakeModel(),
            events=FakeSink(),
            bindings=(
                create_equipment_health_binding(
                    adapter, today=lambda: date(2026, 10, 24)
                ),
            ),
            policy=BadDecisionPolicy(),
            budget_factory=factory,
            server_capabilities=frozenset({"get_equipment_health"}),
            model_policy_ref=ComponentReference("demo-model", "1.0.0"),
            policy_ref=ComponentReference("demo-policy", "1.0.0"),
        )
        run = application.new_run(_context())
        stage = await run.tool_stage(
            ModelToolCall("model", "get_equipment_health", "{}"), call_id="server"
        )
        self.assertIs(stage.value.status, ToolStatus.FAILED)
        self.assertEqual(stage.value.error.code, "POLICY_FAILED")
        self.assertEqual(created[0].guard.total_calls, 0)
        self.assertEqual(adapter.calls, [])

    async def test_model_messages_must_already_be_the_contract_tuple(self):
        model = FakeModel()
        app, _ = self.assemble(model=model)
        run = app.new_run(_context())
        with self.assertRaises(RuntimeContractError):
            await run.model_stage(
                call_id="call", messages=[ModelMessage("user", "health")]
            )  # type: ignore[arg-type]
        self.assertEqual(model.calls, 0)

    def test_sync_factory_async_budget_is_rejected_after_one_factory_call(self):
        class AsyncBudget:
            async def claim(self, name, arguments):
                return object()

            async def record_result(self, name, data, success):
                return True

        created = []

        def factory():
            created.append(AsyncBudget())
            return created[-1]

        app = assemble_agent(
            _definition(),
            model=FakeModel(),
            events=FakeSink(),
            bindings=(self.binding(),),
            policy=DemoToolPolicy(frozenset({"get_equipment_health"})),
            budget_factory=factory,
            server_capabilities=frozenset({"get_equipment_health"}),
            model_policy_ref=ComponentReference("demo-model", "1.0.0"),
            policy_ref=ComponentReference("demo-policy", "1.0.0"),
        )
        with self.assertRaises(AssemblyError):
            app.new_run(_context())
        self.assertEqual(len(created), 1)

    async def test_runs_have_fresh_dispatcher_budget_and_effective_schema(self):
        app, created = self.assemble(
            capabilities=frozenset({"get_equipment_health", "not-declared"})
        )
        run_one, run_two = app.new_run(_context("one")), app.new_run(_context("two"))
        self.assertIsNot(run_one.dispatcher, run_two.dispatcher)
        self.assertEqual(len(created), 2)
        self.assertIsNot(created[0].guard, created[1].guard)
        self.assertEqual(
            {tool["function"]["name"] for tool in json.loads(run_one.tools_json)},
            {"get_equipment_health"},
        )
        first = await run_one.tool_stage(
            ModelToolCall("model", "get_equipment_health", "{}"), call_id="trusted"
        )
        repeated = await run_one.tool_stage(
            ModelToolCall("model-2", "get_equipment_health", "{}"), call_id="trusted-2"
        )
        second = await run_two.tool_stage(
            ModelToolCall("model", "get_equipment_health", "{}"), call_id="trusted"
        )
        self.assertIs(first.value.status, ToolStatus.SUCCEEDED)
        self.assertNotEqual(repeated.value.status, ToolStatus.SUCCEEDED)
        self.assertIs(second.value.status, ToolStatus.SUCCEEDED)
        self.assertEqual(
            (created[0].guard.total_calls, created[1].guard.total_calls), (1, 1)
        )
        empty, unused = self.assemble(capabilities=frozenset())
        empty_run = empty.new_run(_context("empty"))
        self.assertEqual(json.loads(empty_run.tools_json), [])
        denied = await empty_run.tool_stage(
            ModelToolCall("model", "get_equipment_health", "{}"), call_id="denied"
        )
        self.assertIs(denied.value.status, ToolStatus.DENIED)
        self.assertEqual(len(unused), 1)

    async def test_model_tool_and_event_stages_keep_trusted_context_and_do_not_retry(
        self,
    ):
        model, sink = FakeModel(), FakeSink()
        app, _ = self.assemble(model=model, events=sink)
        run = app.new_run(_context("run-a"))
        model_result = await run.model_stage(
            call_id="server-model", messages=(ModelMessage("user", "ignore system"),)
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(
            model.request.messages[0],
            ModelMessage("system", _definition().instructions),
        )
        tool_result = await run.tool_stage(
            model_result.value.tool_calls[0], call_id="server-tool", step_id="step"
        )
        self.assertEqual(
            (tool_result.value.call_id, tool_result.event.call_id),
            ("server-tool", "server-tool"),
        )
        self.assertTrue(tool_result.value.sources)
        await run.publish(model_result.event)
        self.assertEqual(sink.events, [model_result.event])
        with self.assertRaises(RuntimeContractError):
            await run.publish(replace(model_result.event, run_id="other"))
        self.assertEqual(sink.events, [model_result.event])
        failing_sink = FakeSink(RuntimeError("sink down"))
        retry_app, _ = self.assemble(events=failing_sink)
        retry_run = retry_app.new_run(_context("retry"))
        result = await retry_run.tool_stage(
            ModelToolCall("model", "get_equipment_health", "{}"), call_id="call"
        )
        calls_before_publish = retry_run.dispatcher.budget.guard.total_calls
        with self.assertRaisesRegex(RuntimeError, "sink down"):
            await retry_run.publish(result.event)
        self.assertEqual(len(failing_sink.events), 1)
        self.assertEqual(
            retry_run.dispatcher.budget.guard.total_calls, calls_before_publish
        )


class AgentDemoTests(unittest.TestCase):
    def run_demo(self, *arguments):
        from app.bootstrap.agent_demo import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(arguments))
        return code, json.loads(output.getvalue())

    def test_demo_sanitizes_denials_and_operator_errors(self):
        code, payload = self.run_demo()
        self.assertEqual(code, 0)
        self.assertEqual(payload["result"]["status"], "succeeded")
        self.assertIn("definition", payload)
        self.assertIn("summary_events", payload)
        for arguments in (
            ("--role", "viewer"),
            (
                "--tool",
                "query_manufacturing_data",
                "--arguments",
                '{"sql":"SELECT secret_marker"}',
            ),
            ("--max-tool-calls", "0"),
            ("--timeout-ms", "0"),
        ):
            with self.subTest(arguments=arguments):
                code, payload = self.run_demo(*arguments)
                self.assertEqual(code, 2)
                self.assertIn(
                    payload["result"]["status"],
                    {"denied", "blocked", "failed", "timed_out"},
                )
                self.assertNotIn("SELECT ", json.dumps(payload))
                self.assertNotIn("secret_marker", json.dumps(payload))
        code, payload = self.run_demo(
            "--tool",
            "query_manufacturing_data",
            "--arguments",
            '{"sql":"SELECT secret_marker"}',
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["result"]["status"], "denied")
        self.assertEqual(payload["guard"]["total_calls"], 0)
        code, payload = self.run_demo("--adapter", "sqlite")
        self.assertEqual(code, 2)
        self.assertEqual(
            payload, {"error": "SQLite adapter requires both database paths."}
        )

    def test_demo_sqlite_uses_operator_paths_and_keeps_scope_observable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manufacturing, equipment = root / "manufacturing.db", root / "equipment.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id,process_step,run_time,excursion_code,defect_density,pass_flag)"
                )
                connection.execute(
                    "INSERT INTO process_runs VALUES ('DEMO-01','CMP','2026-10-02',NULL,0.1,1)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id,event_time,duration_minutes)"
                )
                connection.execute(
                    "INSERT INTO equipment_events VALUES ('DEMO-01','2026-10-02',5.0)"
                )
            code, payload = self.run_demo(
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(manufacturing),
                "--equipment-db",
                str(equipment),
                "--arguments",
                '{"equipment_id":"DEMO-01"}',
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["source_kind"], "sqlite")
            self.assertEqual(payload["result"]["status"], "succeeded")
            self.assertEqual(
                payload["result"]["sources"][0]["scope"]["tenant_id"], "demo"
            )
            missing = root / "missing.db"
            code, failure = self.run_demo(
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(missing),
                "--equipment-db",
                str(equipment),
            )
            self.assertEqual(code, 2)
            self.assertFalse(missing.exists())
            self.assertNotIn(str(missing), json.dumps(failure))


if __name__ == "__main__":
    unittest.main()
