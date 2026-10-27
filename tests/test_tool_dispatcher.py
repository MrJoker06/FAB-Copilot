from __future__ import annotations

import asyncio
import math
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.agent_runtime.tools.dispatch_contracts import (
    BudgetDecision,
    PolicyDecision,
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "tenant-a"
    user_id: str = "user-a"
    roles: tuple[str, ...] = ("analyst",)


@dataclass(frozen=True)
class Input:
    value: str

    @classmethod
    def from_arguments(cls, arguments):
        value = arguments.get("value")
        if not isinstance(value, str):
            raise TypeError("value")
        return cls(value)

    @classmethod
    def json_schema(cls):
        return {"type": "object"}


class Budget:
    def __init__(self, decision=None, record=True):
        self.decision = BudgetDecision(True) if decision is None else decision
        self.record = record
        self.claims: list[tuple[str, object]] = []
        self.records: list[tuple[str, object, bool]] = []

    def claim(self, name, arguments):
        self.claims.append((name, arguments))
        return self.decision

    def record_result(self, name, data, success):
        self.records.append((name, data, success))
        if isinstance(self.record, Exception):
            raise self.record
        return self.record


class Policy:
    def __init__(self, decision=None):
        self.decision = PolicyDecision(True) if decision is None else decision
        self.calls = []

    def authorize(self, principal, name, scope):
        self.calls.append((principal, name, scope))
        return self.decision


class Cancellation:
    def __init__(self):
        self.cancelled = False

    def is_cancelled(self):
        return self.cancelled


class SignallingBudget(Budget):
    def __init__(self, claimed, **kwargs):
        super().__init__(**kwargs)
        self.claimed = claimed

    def claim(self, name, arguments):
        decision = super().claim(name, arguments)
        self.claimed.set()
        return decision


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    def context(self, **changes):
        values = {
            "principal": Principal(),
            "run_id": "run",
            "call_id": "call",
            "dependencies": object(),
        }
        values.update(changes)
        return ToolExecutionContext(**values)

    def dispatcher(self, binding, *, policy=None, budget=None):
        registry = ToolRegistry()
        registry.register_native(binding)
        return ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=policy or Policy(),
            budget=budget or Budget(),
            allowed_tools=frozenset({binding.definition.name}),
        )

    def binding(self, handler, *, prepare=None, validator=lambda value: value):
        definition = ToolDefinition("native", "v1", "native tool", Input, validator)
        return ToolBinding(definition, handler, {"bound": True}, prepare)

    async def test_typed_success_keeps_payload_identity_and_uses_binding_dependencies(
        self,
    ):
        payload = [{"ok": True}]
        observed = []

        def prepare(value, context):
            observed.append(("prepare", context.dependencies))
            return ToolPreparation(
                value, ToolScope("tenant-a", equipment_ids=("CMP-1",))
            )

        def handler(value, context):
            observed.append(("handler", context.dependencies))
            source = ToolSource(
                "fake:one",
                "fake",
                ToolSourceKind.FAKE,
                ToolScope("tenant-a", equipment_ids=("CMP-1",)),
            )
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                payload,
                sources=(source,),
            )

        policy, budget = Policy(), Budget()
        result = await self.dispatcher(
            self.binding(handler, prepare=prepare), policy=policy, budget=budget
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertIs(result.data, payload)
        self.assertEqual(
            observed, [("prepare", {"bound": True}), ("handler", {"bound": True})]
        )
        self.assertEqual(policy.calls[0][2].equipment_ids, ("CMP-1",))
        self.assertEqual(len(budget.claims), 1)
        self.assertEqual(budget.records, [("native", payload, True)])

    async def test_decode_rejects_non_json_inputs_before_registry_or_budget(self):
        called = []
        binding = self.binding(lambda *_: called.append(True))
        dispatcher = self.dispatcher(binding)
        for raw in ("[]", '{"value": NaN}', ("x",), {1: "x"}):
            with self.subTest(raw=raw):
                result = await dispatcher.dispatch("native", raw, self.context())
                self.assertEqual(result.status, ToolStatus.INVALID_ARGUMENTS)
                self.assertEqual(result.execution_state, ToolExecutionState.NOT_STARTED)
        self.assertEqual(called, [])

    async def test_sql_name_is_denied_without_resolving_registry(self):
        class Registry:
            def resolve(self, name):
                raise AssertionError("registry must not be touched")

        dispatcher = ToolDispatcher(
            run_id="run",
            registry=Registry(),
            policy=Policy(),
            budget=Budget(),
            allowed_tools=frozenset({"native"}),
        )
        result = await dispatcher.dispatch("sql_query", {"value": "x"}, self.context())
        self.assertEqual(
            (result.status, result.execution_state),
            (ToolStatus.DENIED, ToolExecutionState.NOT_STARTED),
        )

    async def test_result_metadata_scope_and_row_limit_are_enforced(self):
        def handler(value, context):
            return ToolResult(
                "wrong",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [1],
            )

        result = await self.dispatcher(self.binding(handler)).dispatch(
            "native", {"value": "x"}, self.context()
        )
        self.assertEqual(result.error.code, "INVALID_RESULT")

        def good(value, context):
            source = ToolSource(
                "fake", "fake", ToolSourceKind.FAKE, ToolScope("tenant-a")
            )
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [1, 2],
                sources=(source,),
            )

        context = self.context(limits=ToolExecutionLimits(max_result_rows=1))
        result = await self.dispatcher(self.binding(good)).dispatch(
            "native", {"value": "x"}, context
        )
        self.assertEqual(result.error.code, "INVALID_RESULT")

    async def test_accounting_failure_converts_a_success_to_completed_internal_failure(
        self,
    ):
        payload = []

        def handler(value, context):
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                payload,
            )

        budget = Budget(record=RuntimeError("secret"))
        result = await self.dispatcher(self.binding(handler), budget=budget).dispatch(
            "native", {"value": "x"}, self.context()
        )
        self.assertEqual(
            (result.status, result.execution_state, result.error.code),
            (ToolStatus.FAILED, ToolExecutionState.COMPLETED, "ACCOUNTING_FAILED"),
        )
        self.assertEqual(len(budget.records), 1)
        self.assertNotIn("secret", result.error.public_message)

    async def test_elapsed_is_finite_nonnegative_for_bad_clock(self):
        def handler(value, context):
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [],
            )

        dispatcher = self.dispatcher(self.binding(handler))
        dispatcher.clock = lambda: math.nan
        result = await dispatcher.dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(result.elapsed_ms, 0.0)

    async def test_handler_errors_are_classified_without_leaking_details(self):
        cases = (
            (
                ToolDataSourceError("database-password"),
                ToolStatus.FAILED,
                "DATA_SOURCE_FAILED",
            ),
            (
                ToolSourceTimeout("secret endpoint"),
                ToolStatus.TIMED_OUT,
                "SOURCE_TIMEOUT",
            ),
            (ValueError("private value"), ToolStatus.FAILED, "TOOL_FAILED"),
        )
        for error, status, code in cases:
            with self.subTest(error=type(error).__name__):

                def handler(value, context, error=error):
                    raise error

                result = await self.dispatcher(self.binding(handler)).dispatch(
                    "native", {"value": "x"}, self.context()
                )
                self.assertEqual(result.status, status)
                if isinstance(error, ToolSourceTimeout):
                    self.assertEqual(result.execution_state, ToolExecutionState.UNKNOWN)
                self.assertEqual(result.error.code, code)
                self.assertNotIn(str(error), result.error.public_message)

    async def test_policy_and_budget_must_return_real_decisions(self):
        class BadPolicy:
            def authorize(self, principal, name, scope):
                return True

        class BadBudget(Budget):
            def claim(self, name, arguments):
                return True

        def handler(value, context):
            raise AssertionError("must not run")

        result = await self.dispatcher(
            self.binding(handler), policy=BadPolicy()
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(result.error.code, "POLICY_FAILED")
        result = await self.dispatcher(
            self.binding(handler), budget=BadBudget()
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(result.error.code, "BUDGET_FAILED")

    async def test_legacy_handler_is_live_patched_and_called_once(self):
        registry = ToolRegistry()
        schema = {
            "type": "function",
            "function": {
                "name": "legacy",
                "description": "x",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }
        registry.initialize_legacy_catalog([schema])
        calls = []
        registry.initialize_legacy_handlers(
            {"legacy": lambda **kwargs: calls.append(kwargs) or {"first": True}}
        )
        dispatcher = ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=Policy(),
            budget=Budget(),
            allowed_tools=frozenset({"legacy"}),
            legacy_tools=frozenset({"legacy"}),
        )
        registry.legacy_handlers["legacy"] = lambda **kwargs: (
            calls.append(kwargs) or {"patched": True}
        )
        result = await dispatcher.dispatch("legacy", {"value": "x"}, self.context())
        self.assertEqual(result.data, {"patched": True})
        self.assertEqual(calls, [{"value": "x"}])

    async def test_running_cancellation_is_unknown_and_late_success_is_not_adopted(
        self,
    ):
        entered, release = threading.Event(), threading.Event()
        cancellation = Cancellation()
        payload = ["late"]

        def handler(value, context):
            entered.set()
            release.wait()
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                payload,
            )

        budget = Budget()
        task = asyncio.create_task(
            self.dispatcher(self.binding(handler), budget=budget).dispatch(
                "native", {"value": "x"}, self.context(cancellation=cancellation)
            )
        )
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
            cancellation.cancelled = True
            result = await asyncio.wait_for(task, timeout=1)
            self.assertEqual(
                (result.status, result.execution_state),
                (ToolStatus.CANCELLED, ToolExecutionState.UNKNOWN),
            )
            self.assertEqual(budget.records, [("native", None, False)])
        finally:
            release.set()
            await asyncio.sleep(0)

    async def test_queued_cancellation_never_starts_the_handler(self):
        occupied, release = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        holder = executor.submit(lambda: (occupied.set(), release.wait()))
        self.assertTrue(occupied.wait(timeout=1))
        asyncio.get_running_loop().set_default_executor(executor)
        claimed = asyncio.Event()
        cancellation, calls = Cancellation(), []
        budget = SignallingBudget(claimed)

        def handler(value, context):
            calls.append(value)
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
            )

        task = asyncio.create_task(
            self.dispatcher(self.binding(handler), budget=budget).dispatch(
                "native", {"value": "x"}, self.context(cancellation=cancellation)
            )
        )
        try:
            await asyncio.wait_for(claimed.wait(), timeout=1)
            cancellation.cancelled = True
            result = await asyncio.wait_for(task, timeout=1)
            self.assertEqual(
                (result.status, result.execution_state),
                (ToolStatus.CANCELLED, ToolExecutionState.NOT_STARTED),
            )
            self.assertEqual(calls, [])
            self.assertEqual(budget.records, [("native", None, False)])
        finally:
            release.set()
            holder.result(timeout=1)
            executor.shutdown(wait=True)
        self.assertEqual(calls, [])
        self.assertEqual(budget.records, [("native", None, False)])

    async def test_queued_deadline_never_starts_the_handler(self):
        occupied, release = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        holder = executor.submit(lambda: (occupied.set(), release.wait()))
        self.assertTrue(occupied.wait(timeout=1))
        asyncio.get_running_loop().set_default_executor(executor)
        claimed = asyncio.Event()
        clock, calls = [0.0], []
        budget = SignallingBudget(claimed)

        def handler(value, context):
            calls.append(value)
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
            )

        dispatcher = self.dispatcher(self.binding(handler), budget=budget)
        dispatcher.clock = lambda: clock[0]
        task = asyncio.create_task(
            dispatcher.dispatch(
                "native",
                {"value": "x"},
                self.context(limits=ToolExecutionLimits(deadline_monotonic=1.0)),
            )
        )
        try:
            await asyncio.wait_for(claimed.wait(), timeout=1)
            clock[0] = 1.0
            result = await asyncio.wait_for(task, timeout=1)
            self.assertEqual(
                (result.status, result.execution_state),
                (ToolStatus.TIMED_OUT, ToolExecutionState.NOT_STARTED),
            )
            self.assertEqual(calls, [])
        finally:
            release.set()
            holder.result(timeout=1)
            executor.shutdown(wait=True)
        self.assertEqual(calls, [])
        self.assertEqual(budget.records, [("native", None, False)])

    async def test_running_deadline_is_unknown_and_late_exception_is_consumed(self):
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        clock = [0.0]
        budget = Budget()
        loop = asyncio.get_running_loop()
        prior_handler, unhandled = loop.get_exception_handler(), []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        def handler(value, context):
            entered.set()
            release.wait()
            finished.set()
            raise RuntimeError("late")

        dispatcher = self.dispatcher(self.binding(handler), budget=budget)
        dispatcher.clock = lambda: clock[0]
        task = asyncio.create_task(
            dispatcher.dispatch(
                "native",
                {"value": "x"},
                self.context(limits=ToolExecutionLimits(deadline_monotonic=1.0)),
            )
        )
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
            clock[0] = 1.0
            result = await asyncio.wait_for(task, timeout=1)
            self.assertEqual(
                (result.status, result.execution_state),
                (ToolStatus.TIMED_OUT, ToolExecutionState.UNKNOWN),
            )
            self.assertEqual(budget.records, [("native", None, False)])
        finally:
            release.set()
            await asyncio.wait_for(asyncio.to_thread(finished.wait), timeout=1)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            loop.set_exception_handler(prior_handler)
        self.assertEqual(
            [
                context
                for context in unhandled
                if "Task exception was never retrieved" in context.get("message", "")
            ],
            [],
        )

    async def test_outer_task_cancellation_propagates_and_records_once(self):
        entered, release = threading.Event(), threading.Event()
        budget = Budget()

        def handler(value, context):
            entered.set()
            release.wait()
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
            )

        task = asyncio.create_task(
            self.dispatcher(self.binding(handler), budget=budget).dispatch(
                "native", {"value": "x"}, self.context()
            )
        )
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(budget.records, [("native", None, False)])
        finally:
            release.set()
            await asyncio.sleep(0)

    async def test_validator_cancellation_gate_cannot_adopt_success(self):
        cancellation = Cancellation()
        budget = Budget()

        def handler(value, context):
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [],
            )

        def validator(data):
            cancellation.cancelled = True
            return data

        result = await self.dispatcher(
            self.binding(handler, validator=validator), budget=budget
        ).dispatch("native", {"value": "x"}, self.context(cancellation=cancellation))
        self.assertEqual(
            (result.status, result.execution_state),
            (ToolStatus.CANCELLED, ToolExecutionState.UNKNOWN),
        )
        self.assertEqual(budget.records, [("native", None, False)])

    def test_demo_policy_rejects_unbounded_equipment_scope(self):
        policy = DemoToolPolicy(
            frozenset({"native"}), equipment_ids=frozenset({"CMP-1"})
        )
        decision = policy.authorize(Principal(), "native", ToolScope("tenant-a"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "SCOPE_DENIED")

    def test_loop_guard_budget_delegates_one_claim_and_duplicate_block(self):
        plan = ExecutionPlan(
            "plan",
            "1",
            "test",
            "ready",
            "",
            "test",
            None,
            None,
            AnalysisScopeContract("fab", (), (), ()),
            (),
            (),
            PlanBudget(2, 2, 1, 10, {"native": 2}, 1, 2),
            (),
            (),
        )
        guard = ToolLoopGuard(plan)
        budget = LoopGuardToolBudget(guard)
        arguments = {"value": "x"}
        self.assertTrue(budget.claim("native", arguments).allowed)
        self.assertEqual(guard.total_calls, 1)
        self.assertTrue(budget.record_result("native", {"evidence": 1}, True))
        duplicate = budget.claim("native", arguments)
        self.assertFalse(duplicate.allowed)
        self.assertEqual(duplicate.code, "duplicate_arguments")
        self.assertEqual(guard.total_calls, 1)

    async def test_prepared_result_metadata_scope_and_validator_fail_closed(self):
        expected_scope = ToolScope("tenant-a", equipment_ids=("CMP-1",))

        def prepare(value, context):
            return ToolPreparation(value, expected_scope)

        cases = (
            (
                "wrong-source-scope",
                lambda: ToolResult(
                    "call",
                    "native",
                    "v1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    ["data"],
                    sources=(
                        ToolSource(
                            "fake", "fake", ToolSourceKind.FAKE, ToolScope("other")
                        ),
                    ),
                ),
            ),
            (
                "missing-source",
                lambda: ToolResult(
                    "call",
                    "native",
                    "v1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    ["data"],
                ),
            ),
            (
                "row-mismatch",
                lambda: ToolResult(
                    "call",
                    "native",
                    "v1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    ["data"],
                    row_count=2,
                ),
            ),
            (
                "version-mismatch",
                lambda: ToolResult(
                    "call",
                    "native",
                    "wrong",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    ["data"],
                ),
            ),
        )
        for label, make_result in cases:
            with self.subTest(label=label):
                budget = Budget()

                def handler(value, context, make_result=make_result):
                    return make_result()

                result = await self.dispatcher(
                    self.binding(handler, prepare=prepare), budget=budget
                ).dispatch("native", {"value": "x"}, self.context())
                self.assertEqual(
                    (result.status, result.error.code, result.data),
                    (ToolStatus.FAILED, "INVALID_RESULT", None),
                )
                self.assertEqual(budget.records, [("native", None, False)])

        payload = ["original"]
        budget = Budget()

        def valid_handler(value, context):
            source = ToolSource("fake", "fake", ToolSourceKind.FAKE, expected_scope)
            return ToolResult(
                "call",
                "native",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                payload,
                sources=(source,),
            )

        def invalid_validator(data):
            self.assertIs(data, payload)
            return ["replacement"]

        result = await self.dispatcher(
            self.binding(valid_handler, prepare=prepare, validator=invalid_validator),
            budget=budget,
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertIs(result.data, payload)

        budget = Budget()
        result = await self.dispatcher(
            self.binding(
                valid_handler,
                prepare=prepare,
                validator=lambda data: (_ for _ in ()).throw(ValueError("bad")),
            ),
            budget=budget,
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(
            (result.status, result.error.code), (ToolStatus.FAILED, "INVALID_RESULT")
        )
        self.assertEqual(budget.records, [("native", None, False)])

    async def test_prepare_and_configuration_errors_do_not_claim_budget(self):
        def handler(value, context):
            raise AssertionError("must not run")

        for error, status, code in (
            (
                ToolInputError("invalid"),
                ToolStatus.INVALID_ARGUMENTS,
                "INVALID_ARGUMENTS",
            ),
            (ValueError("configuration"), ToolStatus.FAILED, "TOOL_PREPARATION_FAILED"),
        ):
            with self.subTest(error=type(error).__name__):
                budget = Budget()
                binding = self.binding(
                    handler,
                    prepare=lambda value, context, error=error: (_ for _ in ()).throw(
                        error
                    ),
                )
                result = await self.dispatcher(binding, budget=budget).dispatch(
                    "native", {"value": "x"}, self.context()
                )
                self.assertEqual((result.status, result.error.code), (status, code))
                self.assertEqual(budget.claims, [])

        class BadInput:
            @classmethod
            def from_arguments(cls, arguments):
                return "not-an-input"

            @classmethod
            def json_schema(cls):
                return {"type": "object"}

        budget = Budget()
        definition = ToolDefinition(
            "native", "v1", "native tool", BadInput, lambda value: value
        )
        result = await self.dispatcher(
            ToolBinding(definition, handler, {}), budget=budget
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(result.error.code, "TOOL_CONFIGURATION")
        self.assertEqual(budget.claims, [])

        class AsyncCallable:
            async def __call__(self, value, context):
                return None

        budget = Budget()
        result = await self.dispatcher(
            self.binding(AsyncCallable()), budget=budget
        ).dispatch("native", {"value": "x"}, self.context())
        self.assertEqual(result.error.code, "TOOL_CONFIGURATION")
        self.assertEqual(budget.claims, [])
