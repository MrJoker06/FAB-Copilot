from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime import service as agent_service
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.ready_dispatch import (
    ReadyDispatchBinding,
    execute_dispatched_ready_plan,
)
from app.agent_runtime.execution.ready_plan import execute_ready_plan
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from app.agent_runtime.execution.runtime_contracts import RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from app.agent_runtime.tools.definition import ToolBinding, ToolDefinition
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.bootstrap import ready_demo
from app.bootstrap.agent_assembly import AssemblyError
from app.bootstrap.ready_assembly import bind_ready_dispatcher
from app.integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.integrations.manufacturing.sqlite_equipment_health import (
    SQLiteEquipmentHealthAdapter,
)
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthQuery,
)
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "ready-test"
    roles: tuple[str, ...] = ("analyst",)


@dataclass(frozen=True)
class Input:
    value: str = "value"

    @classmethod
    def from_arguments(cls, arguments):
        value = arguments.get("value", "value")
        if not isinstance(value, str):
            raise TypeError("value")
        return cls(value)

    @classmethod
    def json_schema(cls):
        return {"type": "object"}


def _plan(*steps: PlanStep, maximum: int = 4) -> ExecutionPlan:
    return ExecutionPlan(
        "ready-dispatch",
        "1",
        "test",
        "ready",
        "",
        "test",
        None,
        None,
        AnalysisScopeContract("fab", (), (), ()),
        (),
        tuple(steps),
        PlanBudget(
            maximum, maximum, 1, 2, {step.tool: maximum for step in steps}, 4, 2
        ),
        (),
        (),
    )


def _step(
    step_id: str, tool: str = "native", *, depends_on=(), limit: int = 2
) -> PlanStep:
    return PlanStep(
        step_id,
        step_id,
        tool,
        {"value": step_id},
        {},
        (),
        tuple(depends_on),
        True,
        (),
        limit,
        "primary",
    )


def _native_binding(name: str, rows: list[dict[str, object]]) -> ToolBinding:
    definition = ToolDefinition(name, "v1", name, Input, lambda value: value)

    def handler(_input, context):
        return ToolResult(
            context.call_id,
            name,
            "v1",
            ToolStatus.SUCCEEDED,
            ToolExecutionState.COMPLETED,
            list(rows),
            sources=(
                ToolSource(
                    f"fake:{name}",
                    "fake",
                    ToolSourceKind.FAKE,
                    ToolScope(context.principal.tenant_id),
                ),
            ),
        )

    return ToolBinding(definition, handler, object())


class ReadyDispatcherTests(unittest.TestCase):
    def _binding(self, plan, dispatcher, policy=None, *, maximum_rows=1):
        guard = dispatcher.budget.guard
        context = RuntimeContext(
            Principal(),
            "run",
            ToolExecutionLimits(remaining_calls=4, max_result_rows=maximum_rows),
        )
        return guard, ReadyDispatchBinding(
            plan,
            guard,
            context,
            dispatcher,
            (policy.take_raw_rows if policy else lambda _call_id: None),
            (policy.extract_sources if policy else lambda _result: ()),
            (policy.clear if policy else lambda: None),
        )

    def _dispatcher(
        self, plan, registry, *, policy=None, allowed=None, legacy=frozenset()
    ):
        return ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=DemoToolPolicy(allowed or frozenset({"native"}), tenant_id="demo"),
            budget=LoopGuardToolBudget(ToolLoopGuard(plan)),
            allowed_tools=allowed or frozenset({"native"}),
            legacy_tools=legacy,
            result_policy=policy,
        )

    def test_invalid_graph_is_rejected_before_events_claims_or_dispatch(self):
        invalid_plans = (
            (_plan(_step("S01", depends_on=("missing",))), "未知依赖"),
            (
                _plan(
                    _step("S01", depends_on=("S02",)),
                    _step("S02", depends_on=("S01",)),
                ),
                "循环依赖",
            ),
            (_plan(_step("S01"), _step("S01")), "重复 step_id"),
        )
        for plan, error in invalid_plans:
            with self.subTest(error=error):
                registry = ToolRegistry()
                registry.register_native(_native_binding("native", []))
                dispatcher = self._dispatcher(plan, registry)
                guard, binding = self._binding(plan, dispatcher)
                events = []

                async def notify(*_args):
                    raise AssertionError("invalid graph must not notify")

                with self.assertRaisesRegex(ValueError, error):
                    asyncio.run(
                        execute_dispatched_ready_plan(
                            plan,
                            guard,
                            "run",
                            None,
                            binding=binding,
                            notify=notify,
                            emit_event=lambda *args, events=events, **kwargs: (
                                events.append((args, kwargs))
                            ),
                        )
                    )
                self.assertEqual((guard.total_calls, events), (0, []))

    def test_ready_injection_preserves_old_round_stop_reason_after_projection(self):
        async def notify(*_args):
            return None

        for maximum, no_progress, expected in (
            (1, 1, "total_tool_budget_exhausted"),
            (2, 1, "no_progress"),
        ):
            with self.subTest(maximum=maximum, no_progress=no_progress):
                plan = _plan(_step("S01", "search"), maximum=maximum)
                plan = replace(
                    plan,
                    budget=replace(plan.budget, max_no_progress_rounds=no_progress),
                )
                old_guard = ToolLoopGuard(plan)
                asyncio.run(
                    execute_ready_plan(
                        plan,
                        old_guard,
                        "run",
                        None,
                        execute_tool=lambda *_args: [],
                        notify=notify,
                        emit_event=lambda *_args, **_kwargs: None,
                        usable_knowledge_result=lambda *_args: False,
                    )
                )

                registry = ToolRegistry()
                registry.register_native(
                    _native_binding("search", [{"reference_id": "discard"}])
                )
                projector = ReadyResultPolicy(
                    frozenset({"search"}), lambda *_args: False
                )
                dispatcher = self._dispatcher(
                    plan,
                    registry,
                    policy=projector,
                    allowed=frozenset({"search"}),
                )
                new_guard, binding = self._binding(plan, dispatcher, projector)
                outcome = asyncio.run(
                    execute_dispatched_ready_plan(
                        plan,
                        new_guard,
                        "run",
                        None,
                        binding=binding,
                        notify=notify,
                        emit_event=lambda *_args, **_kwargs: None,
                    )
                )
                self.assertEqual(outcome.tool_results[0].data, [])
                self.assertEqual(
                    (old_guard.stop_reason, new_guard.stop_reason),
                    (expected, expected),
                )

    def test_actual_dispatcher_projects_final_rows_scope_and_single_guard_accounting(
        self,
    ):
        step = _step("S01", "native", limit=3)
        plan = _plan(step)
        registry = ToolRegistry()
        registry.register_native(
            _native_binding("native", [{"n": 1}, {"n": 2}, {"n": 3}])
        )
        policy = ReadyResultPolicy()
        dispatcher = self._dispatcher(plan, registry, policy=policy)
        guard, binding = self._binding(plan, dispatcher, policy)
        notifications = []

        async def notify(_progress, event):
            notifications.append(event)

        trace, observations, sources = asyncio.run(
            execute_ready_plan(
                plan,
                guard,
                "run",
                None,
                dispatch_binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
                usable_knowledge_result=lambda _query, _item: True,
            )
        )
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(len(guard.evidence_fingerprints), 1)
        self.assertEqual(trace[0]["raw_rows"], 3)
        self.assertEqual(trace[0]["row_count"], 1)
        self.assertEqual(observations[0].source_ref, "TOOL:S01")
        self.assertEqual(observations[0].arguments, {"value": "S01"})
        self.assertEqual(sources, {})
        self.assertEqual(
            [event["event"] for event in notifications],
            ["tool_started", "tool_finished"],
        )

    def test_service_facade_injects_dispatcher_without_calling_legacy_executor(self):
        plan = _plan(_step("S01"))
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", [{"ok": True}]))
        projector = ReadyResultPolicy()
        dispatcher = self._dispatcher(plan, registry, policy=projector)
        guard, binding = self._binding(plan, dispatcher, projector)

        async def run() -> tuple[list[dict], list[object], dict[str, dict]]:
            with (
                patch.object(
                    agent_service,
                    "_execute_registered_tool",
                    side_effect=AssertionError("legacy executor must not run"),
                ),
                patch.object(agent_service, "emit"),
            ):
                return await agent_service._execute_ready_plan(
                    plan, guard, "run", None, dispatch_binding=binding
                )

        trace, observations, sources = asyncio.run(run())
        self.assertEqual((guard.total_calls, len(guard.evidence_fingerprints)), (1, 1))
        self.assertEqual(trace[0]["status"], "ok")
        self.assertEqual(observations[0].source_ref, "TOOL:S01")
        self.assertEqual(sources, {})

    def test_failed_parent_blocks_child_without_dispatch_or_budget_claim(self):
        parent, child = _step("S01", "missing"), _step("S02", depends_on=("S01",))
        plan = _plan(parent, child)
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", []))
        dispatcher = self._dispatcher(
            plan, registry, allowed=frozenset({"missing", "native"})
        )
        guard, binding = self._binding(plan, dispatcher)

        async def notify(*_args):
            return None

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                "run",
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual([row["status"] for row in outcome.trace], ["error", "blocked"])
        self.assertEqual(outcome.trace[1]["execution_state"], "not_started")
        self.assertEqual(guard.total_calls, 0)

    def test_contract_mismatch_is_rejected_before_dispatch(self):
        plan = _plan(_step("S01"))
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", []))
        dispatcher = self._dispatcher(plan, registry)
        guard, binding = self._binding(plan, dispatcher)
        wrong = replace(binding, context=RuntimeContext(Principal(), "other"))

        async def notify(*_args):
            raise AssertionError("mismatch must not notify")

        with self.assertRaisesRegex(Exception, "Ready dispatch contract"):
            asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    guard,
                    "run",
                    None,
                    binding=wrong,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(guard.total_calls, 0)

    def test_one_dispatcher_runs_live_legacy_and_native_bindings(self):
        legacy, native = (
            _step("S01", "legacy"),
            _step("S02", "native", depends_on=("S01",)),
        )
        plan = _plan(legacy, native)
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "legacy",
                        "description": "legacy",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                        },
                    },
                }
            ]
        )
        calls = []
        registry.initialize_legacy_handlers(
            {"legacy": lambda **kwargs: calls.append(kwargs) or [{"legacy": 1}]}
        )
        registry.register_native(_native_binding("native", [{"native": 1}]))
        dispatcher = self._dispatcher(
            plan,
            registry,
            allowed=frozenset({"legacy", "native"}),
            legacy=frozenset({"legacy"}),
        )
        guard, binding = self._binding(plan, dispatcher)

        async def notify(*_args):
            return None

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                "run",
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual(calls, [{"value": "S01"}])
        self.assertEqual([item["status"] for item in outcome.trace], ["ok", "ok"])
        self.assertEqual(guard.total_calls, 2)

    def test_health_binding_fake_and_sqlite_use_ready_entry_effective_scope_and_tool_ref(
        self,
    ):
        step = replace(
            _step("S01", "get_equipment_health"), parameters={"equipment_id": "cmp-01"}
        )
        plan = _plan(step)
        expected = EquipmentHealthQuery(
            date(2026, 7, 27), date(2026, 10, 24), equipment_id="CMP-01"
        )
        aggregate = EquipmentHealthAggregate("CMP-01", 8, 1, 0.2, 98.0, 1, 3.0)
        fake = FakeEquipmentHealthAdapter("demo", {expected: (aggregate,)})

        def run(binding):
            registry = ToolRegistry()
            registry.register_native(binding)
            projector = ReadyResultPolicy()
            dispatcher = self._dispatcher(
                plan, registry, policy=projector, allowed=frozenset({step.tool})
            )
            guard, ready = self._binding(plan, dispatcher, projector)

            async def notify(*_args):
                return None

            return asyncio.run(
                execute_ready_plan(
                    plan,
                    guard,
                    "run",
                    None,
                    dispatch_binding=ready,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                    usable_knowledge_result=lambda _query, _item: True,
                )
            )

        fake_trace, fake_observations, _ = run(
            create_equipment_health_binding(fake, today=lambda: date(2026, 10, 24))
        )
        self.assertEqual(fake.calls, [expected])
        self.assertEqual(fake_observations[0].source_ref, "TOOL:S01")
        self.assertEqual(
            fake_observations[0].arguments,
            {"equipment_id": "CMP-01", "start": "2026-07-27", "end": "2026-10-24"},
        )
        self.assertEqual(
            fake_trace[0]["sources"][0]["scope"]["equipment_ids"], ["CMP-01"]
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manufacturing, equipment = root / "m.db", root / "e.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
                )
                connection.execute(
                    "INSERT INTO process_runs VALUES ('CMP-01','CMP','2026-10-02',NULL,0.2,1)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
                )
            sqlite_trace, sqlite_observations, _ = run(
                create_equipment_health_binding(
                    SQLiteEquipmentHealthAdapter(
                        manufacturing, equipment, demo_tenant_id="demo"
                    ),
                    today=lambda: date(2026, 10, 24),
                )
            )
        self.assertEqual(sqlite_observations[0].source_ref, "TOOL:S01")
        self.assertEqual(sqlite_observations[0].arguments["equipment_id"], "CMP-01")
        self.assertEqual(
            sqlite_trace[0]["sources"][0]["scope"]["equipment_ids"], ["CMP-01"]
        )

    def test_guard_methods_are_called_once_per_actual_failure_and_child_is_not_invoked(
        self,
    ):
        parent, child = _step("S01"), _step("S02", depends_on=("S01",))
        plan = _plan(parent, child)
        registry = ToolRegistry()
        definition = ToolDefinition(
            "native", "v1", "native", Input, lambda value: value
        )

        def fail(_input, _context):
            from app.agent_runtime.tools.dispatch_contracts import ToolDataSourceError

            raise ToolDataSourceError("source")

        registry.register_native(ToolBinding(definition, fail, object()))
        legacy_sentinel = []
        registry.legacy_handlers["native"] = lambda **_kwargs: legacy_sentinel.append(
            True
        )
        dispatcher = self._dispatcher(plan, registry)
        guard, binding = self._binding(plan, dispatcher)

        async def notify(*_args):
            return None

        with (
            patch.object(guard, "begin_round", wraps=guard.begin_round) as begin,
            patch.object(guard, "finish_round", wraps=guard.finish_round) as finish,
            patch.object(guard, "check_call", wraps=guard.check_call) as check,
            patch.object(guard, "record_result", wraps=guard.record_result) as record,
        ):
            outcome = asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    guard,
                    "run",
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual([row["status"] for row in outcome.trace], ["error", "blocked"])
        self.assertEqual(
            (begin.call_count, finish.call_count, check.call_count, record.call_count),
            (1, 1, 1, 1),
        )
        self.assertEqual(record.call_args.args[1:], (None, False))
        self.assertEqual(legacy_sentinel, [])

    def test_knowledge_projection_uses_final_rows_and_live_legacy_patch_is_read_each_call(
        self,
    ):
        step = replace(
            _step("S01", "search"),
            parameters={"query": "cmp"},
            estimated_result_limit=1,
        )
        plan = _plan(step)
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "search",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                }
            ]
        )
        old_calls, new_calls = [], []
        registry.initialize_legacy_handlers(
            {
                "search": lambda **kwargs: (
                    old_calls.append(kwargs) or [{"reference_id": "OLD"}]
                )
            }
        )
        registry.legacy_handlers["search"] = lambda **kwargs: (
            new_calls.append(kwargs)
            or [
                {"reference_id": "BAD", "confidence": 0.1},
                {"reference_id": "GOOD-1", "confidence": 0.9},
                {"reference_id": "GOOD-2", "confidence": 0.9},
            ]
        )
        projector = ReadyResultPolicy(
            frozenset({"search"}), lambda _query, item: item.get("confidence") == 0.9
        )
        dispatcher = self._dispatcher(
            plan,
            registry,
            policy=projector,
            allowed=frozenset({"search"}),
            legacy=frozenset({"search"}),
        )
        guard, binding = self._binding(plan, dispatcher, projector)

        async def notify(*_args):
            return None

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                "run",
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual((old_calls, new_calls), ([], [{"query": "cmp"}]))
        self.assertEqual(outcome.trace[0]["raw_rows"], 3)
        self.assertEqual(
            outcome.tool_results[0].data,
            [{"reference_id": "GOOD-1", "confidence": 0.9}],
        )
        self.assertEqual(
            outcome.sources, {"GOOD-1": {"reference_id": "GOOD-1", "confidence": 0.9}}
        )
        self.assertEqual(len(guard.evidence_fingerprints), 1)

    def test_sql_is_denied_without_secret_in_events_trace_or_observation(self):
        step = replace(_step("S01", "sql"), parameters={"sql": "SELECT secret_marker"})
        plan = _plan(step)
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", []))
        dispatcher = self._dispatcher(plan, registry, allowed=frozenset({"native"}))
        guard, binding = self._binding(plan, dispatcher)
        events = []

        async def notify(_progress, event):
            events.append(event)

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                "run",
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda name, _run, **details: events.append(
                    {"event": name, **details}
                ),
            )
        )
        rendered = repr((events, outcome.trace, outcome.observation_payloads))
        self.assertEqual(guard.total_calls, 0)
        self.assertEqual(outcome.trace[0]["status"], "blocked")
        self.assertNotIn("secret_marker", rendered)

    def test_notify_failure_after_success_propagates_without_second_execution_or_record(
        self,
    ):
        plan = _plan(_step("S01"))
        registry = ToolRegistry()
        calls = []
        definition = ToolDefinition(
            "native", "v1", "native", Input, lambda value: value
        )

        def handler(_input, context):
            calls.append(context.call_id)
            return ToolResult(
                context.call_id,
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [{"ok": True}],
            )

        registry.register_native(ToolBinding(definition, handler, object()))
        dispatcher = self._dispatcher(plan, registry)
        guard, binding = self._binding(plan, dispatcher)

        async def notify(_progress, event):
            if event["event"] == "tool_finished":
                raise RuntimeError("observer down")

        with (
            patch.object(guard, "record_result", wraps=guard.record_result) as record,
            self.assertRaisesRegex(RuntimeError, "observer down"),
        ):
            asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    guard,
                    "run",
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(calls, ["plan-S01"])
        self.assertEqual(record.call_count, 1)
        self.assertEqual(record.call_args.args[1:], ([{"ok": True}], True))

        fresh_dispatcher = self._dispatcher(plan, registry)
        fresh_guard, fresh_binding = self._binding(plan, fresh_dispatcher)

        async def no_op_notify(*_args):
            return None

        with self.assertRaisesRegex(RuntimeError, "sink down"):
            asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    fresh_guard,
                    "run",
                    None,
                    binding=fresh_binding,
                    notify=no_op_notify,
                    emit_event=lambda name, *_args, **_kwargs: (
                        (_ for _ in ()).throw(RuntimeError("sink down"))
                        if name == "tool_call_finished"
                        else None
                    ),
                )
            )
        self.assertEqual(calls, ["plan-S01", "plan-S01"])
        self.assertEqual(fresh_guard.total_calls, 1)

    def test_ready_assembly_rejects_guard_plan_and_projector_identity_mismatches(self):
        plan = _plan(_step("S01"))
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", []))
        projector = ReadyResultPolicy()
        dispatcher = self._dispatcher(plan, registry, policy=projector)
        guard, binding = self._binding(plan, dispatcher, projector)
        with self.assertRaises(AssemblyError):
            bind_ready_dispatcher(
                plan, ToolLoopGuard(plan), binding.context, dispatcher, projector
            )
        with self.assertRaises(AssemblyError):
            bind_ready_dispatcher(
                plan, guard, binding.context, dispatcher, ReadyResultPolicy()
            )

    def test_deadline_before_start_and_running_timeout_preserve_dispatch_states(self):
        plan = _plan(_step("S01"))
        registry = ToolRegistry()
        registry.register_native(_native_binding("native", []))
        dispatcher = self._dispatcher(plan, registry)
        guard, binding = self._binding(plan, dispatcher)
        expired = replace(
            binding,
            context=RuntimeContext(
                Principal(), "run", ToolExecutionLimits(deadline_monotonic=0.0)
            ),
        )

        async def notify(*_args):
            return None

        outcome = asyncio.run(
            execute_dispatched_ready_plan(
                plan,
                guard,
                "run",
                None,
                binding=expired,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual(
            (outcome.trace[0]["execution_state"], guard.total_calls),
            ("not_started", 0),
        )

        class Cancelled:
            def is_cancelled(self) -> bool:
                return True

        cancelled_dispatcher = self._dispatcher(plan, registry)
        cancelled_guard, cancelled_binding = self._binding(plan, cancelled_dispatcher)
        cancelled_binding = replace(
            cancelled_binding,
            context=RuntimeContext(
                Principal(),
                "run",
                ToolExecutionLimits(remaining_calls=4, max_result_rows=1),
                Cancelled(),
            ),
        )
        with patch.object(
            cancelled_guard, "check_call", wraps=cancelled_guard.check_call
        ) as claim:
            cancelled = asyncio.run(
                execute_dispatched_ready_plan(
                    plan,
                    cancelled_guard,
                    "run",
                    None,
                    binding=cancelled_binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(
            (cancelled.trace[0]["execution_state"], cancelled_guard.total_calls),
            ("not_started", 0),
        )
        self.assertEqual(claim.call_count, 0)

        entered, release, clock = threading.Event(), threading.Event(), [0.0]
        running_registry = ToolRegistry()
        definition = ToolDefinition(
            "native", "v1", "native", Input, lambda value: value
        )

        def block(_input, _context):
            entered.set()
            release.wait()
            return ToolResult(
                "plan-S01",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [{"late": True}],
            )

        running_registry.register_native(ToolBinding(definition, block, object()))
        running_dispatcher = self._dispatcher(plan, running_registry)
        running_dispatcher.clock = lambda: clock[0]
        running_guard, running_binding = self._binding(plan, running_dispatcher)
        running_binding = replace(
            running_binding,
            context=RuntimeContext(
                Principal(), "run", ToolExecutionLimits(deadline_monotonic=1.0)
            ),
        )

        async def run_timeout():
            task = asyncio.create_task(
                execute_dispatched_ready_plan(
                    plan,
                    running_guard,
                    "run",
                    None,
                    binding=running_binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
                clock[0] = 1.0
                return await asyncio.wait_for(task, timeout=1)
            finally:
                release.set()

        timed = asyncio.run(run_timeout())
        self.assertEqual(
            (timed.trace[0]["execution_state"], running_guard.total_calls),
            ("unknown", 1),
        )
        self.assertEqual(len(running_guard.evidence_fingerprints), 0)

    def test_outer_cancellation_propagates_and_late_result_never_advances_guard(self):
        plan = _plan(_step("S01"))
        entered, release, completed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        registry = ToolRegistry()
        definition = ToolDefinition(
            "native", "v1", "native", Input, lambda value: value
        )

        def block(_input, context):
            entered.set()
            release.wait()
            try:
                return ToolResult(
                    context.call_id,
                    "native",
                    "v1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    [{"late": True}],
                )
            finally:
                completed.set()

        registry.register_native(ToolBinding(definition, block, object()))
        dispatcher = self._dispatcher(plan, registry)
        guard, binding = self._binding(plan, dispatcher)
        events = []
        emitted = []

        async def notify(_progress, event):
            events.append(event["event"])

        async def run_and_cancel():
            task = asyncio.create_task(
                execute_dispatched_ready_plan(
                    plan,
                    guard,
                    "run",
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda name, *_args, **_kwargs: emitted.append(name),
                )
            )
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
                with patch.object(
                    guard, "record_result", wraps=guard.record_result
                ) as record:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(record.call_count, 1)
            finally:
                release.set()
                await asyncio.wait_for(asyncio.to_thread(completed.wait), timeout=1)

        asyncio.run(run_and_cancel())
        self.assertEqual((guard.total_calls, len(guard.evidence_fingerprints)), (1, 0))
        self.assertEqual(events, ["tool_started"])
        self.assertNotIn("ready_plan_execution_finished", emitted)

    def test_ready_demo_sqlite_uses_scope_and_sql_rejection_does_not_echo_query(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manufacturing, equipment = root / "m.db", root / "e.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
                )
                connection.execute(
                    "INSERT INTO process_runs VALUES ('CMP-01','CMP','2026-10-02',NULL,0.2,1)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
                )
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = ready_demo.main(
                    [
                        "--adapter",
                        "sqlite",
                        "--manufacturing-db",
                        str(manufacturing),
                        "--equipment-db",
                        str(equipment),
                        "--as-of",
                        "2026-10-24",
                        "--arguments",
                        '{"equipment_id":"CMP-01"}',
                    ]
                )
            payload = json.loads(stream.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["model_tool_selection_calls"], 0)
            self.assertEqual(
                payload["observations"][0]["arguments"]["equipment_id"], "CMP-01"
            )

            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                rejected = ready_demo.main(
                    [
                        "--tool",
                        "sql",
                        "--arguments",
                        '{"sql":"SELECT secret_marker"}',
                    ]
                )
            self.assertEqual(rejected, 2)
            self.assertNotIn("secret_marker", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
