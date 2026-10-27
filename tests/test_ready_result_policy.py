from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, replace

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
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
from app.agent_runtime.tools.definition import ToolBinding, ToolDefinition
from app.agent_runtime.tools.dispatch_contracts import BudgetDecision, PolicyDecision
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "tenant"
    user_id: str = "user"
    roles: tuple[str, ...] = ("analyst",)


@dataclass(frozen=True)
class Input:
    query: str

    @classmethod
    def from_arguments(cls, arguments: dict[str, object]) -> Input:
        query = arguments.get("query")
        if not isinstance(query, str):
            raise ValueError  # noqa: TRY004 - dispatcher treats parsed input as invalid
        return cls(query)

    @classmethod
    def json_schema(cls) -> dict[str, str]:
        return {"type": "object"}


class AllowPolicy:
    def authorize(self, principal, name, scope):
        return PolicyDecision(True)


class Budget:
    def __init__(self) -> None:
        self.claims = 0
        self.records: list[tuple[object, bool]] = []

    def claim(self, name, arguments):
        self.claims += 1
        return BudgetDecision(True)

    def record_result(self, name, data, success):
        self.records.append((data, success))


class Cancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def is_cancelled(self) -> bool:
        return self.cancelled


def _binding(handler):
    return ToolBinding(
        ToolDefinition("tool", "v1", "tool", Input, lambda value: value),
        handler,
        object(),
    )


def _context(*, limits=None):
    return ToolExecutionContext(
        Principal(), "run", "call", object(), limits=limits or ToolExecutionLimits()
    )


def _dispatcher(handler, budget, *, result_policy=None):
    registry = ToolRegistry()
    registry.register_native(_binding(handler))
    return ToolDispatcher(
        run_id="run",
        registry=registry,
        policy=AllowPolicy(),
        budget=budget,
        allowed_tools=frozenset({"tool"}),
        result_policy=result_policy,
    )


def _result(data, *, sources=()):
    return ToolResult(
        "call",
        "tool",
        "v1",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=data,
        sources=sources,
    )


class ReadyResultPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_dispatcher_retains_raw_row_limit_failure(self):
        budget = Budget()
        result = await _dispatcher(lambda *_: _result([1, 2]), budget).dispatch(
            "tool",
            {"query": "q"},
            _context(limits=ToolExecutionLimits(max_result_rows=1)),
        )
        self.assertEqual(result.status, ToolStatus.FAILED)
        self.assertEqual(result.error.code, "INVALID_RESULT")
        self.assertEqual(budget.records, [(None, False)])

    async def test_policy_truncates_before_accounting_and_keeps_raw_diagnostic(self):
        policy = ReadyResultPolicy()
        budget = Budget()
        result = await _dispatcher(
            lambda *_: _result([1, 2]), budget, result_policy=policy
        ).dispatch(
            "tool",
            {"query": "q"},
            _context(limits=ToolExecutionLimits(max_result_rows=1)),
        )
        self.assertEqual(result.data, [1])
        self.assertEqual(result.row_count, 1)
        self.assertEqual(policy.take_raw_rows("call"), 2)
        self.assertIsNone(policy.take_raw_rows("call"))
        self.assertEqual(budget.records, [([1], True)])

    async def test_knowledge_filter_copies_data_and_extracts_references(self):
        raw = [{"reference_id": "good"}, {"reference_id": "bad"}, "invalid"]
        policy = ReadyResultPolicy(
            frozenset({"tool"}),
            lambda query, item: (
                query == "needle" and item.get("reference_id") == "good"
            ),
        )
        budget = Budget()
        result = await _dispatcher(
            lambda *_: _result(raw), budget, result_policy=policy
        ).dispatch("tool", {"query": "needle"}, _context())
        self.assertEqual(result.data, [{"reference_id": "good"}])
        self.assertIsNot(result.data, raw)
        self.assertEqual(policy.extract_sources(result), ({"reference_id": "good"},))
        self.assertEqual(
            raw, [{"reference_id": "good"}, {"reference_id": "bad"}, "invalid"]
        )

    async def test_knowledge_filter_applies_limit_and_records_final_data(self):
        policy = ReadyResultPolicy(
            frozenset({"tool"}), lambda _query, item: item.get("confidence") == "high"
        )
        plan = ExecutionPlan(
            "p",
            "1",
            "x",
            "ready",
            "",
            "",
            None,
            None,
            AnalysisScopeContract("equipment", (), (), ()),
            (),
            (),
            PlanBudget(1, 1, 1, 3, {"tool": 1}, 1, 1),
            (),
            (),
        )
        guard = ToolLoopGuard(plan)
        raw = [
            {"reference_id": "a", "confidence": "high"},
            {"reference_id": "b", "confidence": "high"},
            {"reference_id": "c", "confidence": "high"},
            {"reference_id": "low", "confidence": "low"},
        ]
        result = await _dispatcher(
            lambda *_: _result(raw), LoopGuardToolBudget(guard), result_policy=policy
        ).dispatch(
            "tool",
            {"query": "q"},
            _context(limits=ToolExecutionLimits(max_result_rows=1)),
        )
        self.assertEqual(policy.take_raw_rows("call"), 4)
        self.assertEqual((result.data, result.row_count), ([raw[0]], 1))
        self.assertEqual(policy.extract_sources(result), (raw[0],))
        self.assertEqual(len(guard.evidence_fingerprints), 1)

    async def test_tuple_payload_retains_core_row_count(self):
        result = await _dispatcher(
            lambda *_: _result((1, 2)), Budget(), result_policy=ReadyResultPolicy()
        ).dispatch("tool", {"query": "q"}, _context())
        self.assertEqual((result.data, result.row_count), ((1, 2), 2))

    async def test_bad_policy_metadata_exception_and_awaitable_are_sanitized(self):
        source = ToolSource("fake", "adapter", ToolSourceKind.FAKE, ToolScope("tenant"))

        class ChangeSource:
            def finalize(self, result, arguments, limits):
                return replace(result, sources=())

        class Explodes:
            def finalize(self, result, arguments, limits):
                raise RuntimeError("secret")

        class Awaitable:
            def finalize(self, result, arguments, limits):
                async def later():
                    return result

                return later()

        for policy, code in (
            (ChangeSource(), "INVALID_RESULT"),
            (Explodes(), "RESULT_POLICY_FAILED"),
            (Awaitable(), "INVALID_RESULT"),
        ):
            with self.subTest(policy=type(policy).__name__):
                budget = Budget()
                result = await _dispatcher(
                    lambda *_: _result([1], sources=(source,)),
                    budget,
                    result_policy=policy,
                ).dispatch("tool", {"query": "q"}, _context())
                self.assertEqual(
                    (result.status, result.execution_state, result.error.code),
                    (ToolStatus.FAILED, ToolExecutionState.COMPLETED, code),
                )
                self.assertNotIn("secret", result.error.public_message)
                self.assertEqual(budget.records, [(None, False)])

    async def test_denied_and_invalid_calls_never_invoke_policy_or_budget(self):
        class Counting:
            def __init__(self):
                self.calls = 0

            def finalize(self, result, arguments, limits):
                self.calls += 1
                return result

        policy, budget = Counting(), Budget()
        dispatcher = _dispatcher(lambda *_: _result([1]), budget, result_policy=policy)
        invalid = await dispatcher.dispatch("tool", {"query": 2}, _context())
        self.assertEqual(invalid.status, ToolStatus.INVALID_ARGUMENTS)
        denied = await dispatcher.dispatch("other", {"query": "q"}, _context())
        self.assertEqual(denied.status, ToolStatus.DENIED)
        self.assertEqual(policy.calls, 0)
        self.assertEqual(budget.claims, 0)

    async def test_cancelled_completion_does_not_finalize_or_record_progress(self):
        class Counting:
            def __init__(self):
                self.calls = 0

            def finalize(self, result, arguments, limits):
                self.calls += 1
                return result

        cancellation, policy, budget = Cancellation(), Counting(), Budget()

        def handler(value, context):
            cancellation.cancelled = True
            return _result([1])

        context = ToolExecutionContext(
            Principal(), "run", "call", object(), cancellation=cancellation
        )
        result = await _dispatcher(handler, budget, result_policy=policy).dispatch(
            "tool", {"query": "q"}, context
        )
        self.assertEqual(result.status, ToolStatus.CANCELLED)
        self.assertEqual(policy.calls, 0)
        self.assertEqual(budget.records, [(None, False)])

    def test_async_finalize_is_rejected_at_dispatcher_construction(self):
        class AsyncPolicy:
            async def finalize(self, result, arguments, limits):
                return result

        with self.assertRaises(ValueError):
            _dispatcher(lambda *_: _result([]), Budget(), result_policy=AsyncPolicy())

        class CallableAsyncFinalize:
            async def __call__(self, result, arguments, limits):
                return result

        class CallableAsyncPolicy:
            finalize = CallableAsyncFinalize()

        with self.assertRaises(ValueError):
            _dispatcher(
                lambda *_: _result([]), Budget(), result_policy=CallableAsyncPolicy()
            )

    async def test_policy_cancellation_records_failure_once_then_propagates(self):
        class Cancel:
            def finalize(self, result, arguments, limits):
                raise asyncio.CancelledError

        budget = Budget()
        with self.assertRaises(asyncio.CancelledError):
            await _dispatcher(
                lambda *_: _result([1]), budget, result_policy=Cancel()
            ).dispatch("tool", {"query": "q"}, _context())
        self.assertEqual(budget.records, [(None, False)])

    async def test_loop_guard_records_projected_result_once_without_progress_for_empty_filter(
        self,
    ):
        plan = ExecutionPlan(
            "p",
            "1",
            "x",
            "ready",
            "",
            "",
            None,
            None,
            AnalysisScopeContract("equipment", (), (), ()),
            (),
            (),
            PlanBudget(1, 1, 1, 3, {"tool": 1}, 1, 1),
            (),
            (),
        )
        guard = ToolLoopGuard(plan)
        policy = ReadyResultPolicy(frozenset({"tool"}), lambda *_: False)
        result = await _dispatcher(
            lambda *_: _result([{"reference_id": "discard"}]),
            LoopGuardToolBudget(guard),
            result_policy=policy,
        ).dispatch("tool", {"query": "q"}, _context())
        self.assertEqual(result.data, [])
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(len(guard.evidence_fingerprints), 0)


if __name__ == "__main__":
    unittest.main()
