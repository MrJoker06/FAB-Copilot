from __future__ import annotations

import asyncio
import inspect
import typing
import unittest
from dataclasses import dataclass, fields, is_dataclass
from datetime import date

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.pilot_stages import (
    execute_model_stage,
    execute_tool_stage,
    publish_stage_event,
)
from app.agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
    RuntimeContext,
    RuntimeContractError,
    RuntimeEvent,
    StageResult,
)
from app.agent_runtime.execution.runtime_ports import (
    EventSink,
    ModelResponsePort,
    ToolDispatcherPort,
)
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolError,
    ToolErrorKind,
    ToolExecutionContext,
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
)
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.integrations.manufacturing.fake_equipment_health import demo_fake_adapter
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
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


class Cancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def is_cancelled(self) -> bool:
        return self.cancelled


class FakeModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0
        self.request: ModelRequest | None = None
        self.context: RuntimeContext | None = None

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        self.calls += 1
        self.request, self.context = request, context
        return self.response  # type: ignore[return-value]


class FakeDispatcher:
    def __init__(self, result: ToolResult[object]) -> None:
        self.result: ToolResult[object] = result
        self.calls = 0
        self.seen: tuple[str, object, ToolExecutionContext[None]] | None = None

    async def dispatch(
        self, name: str, raw_arguments: object, context: ToolExecutionContext[None]
    ) -> ToolResult[object]:
        self.calls += 1
        self.seen = name, raw_arguments, context
        return self.result


class RecordingDispatcher:
    def __init__(self, delegate: ToolDispatcher) -> None:
        self.delegate = delegate
        self.calls = 0
        self.context: ToolExecutionContext[None] | None = None
        self.result: ToolResult[object] | None = None

    async def dispatch(
        self, name: str, raw_arguments: object, context: ToolExecutionContext[None]
    ) -> ToolResult[object]:
        self.calls += 1
        self.context = context
        self.result = await self.delegate.dispatch(name, raw_arguments, context)
        return self.result


class FakeSink:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.events: list[RuntimeEvent] = []

    async def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)
        if self.error is not None:
            raise self.error


def _plan(calls: int = 1) -> ExecutionPlan:
    return ExecutionPlan(
        "runtime-ports",
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


class RuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    def context(self) -> RuntimeContext:
        self.limits = ToolExecutionLimits(remaining_calls=1, max_result_rows=5)
        self.cancellation = Cancellation()
        return RuntimeContext(Principal(), "run-1", self.limits, self.cancellation)

    def request(self) -> ModelRequest:
        return ModelRequest(
            "provider-call",
            (
                ModelMessage("system", "keep outputs concise"),
                ModelMessage("user", "health"),
            ),
            '[{"type":"function","function":{"name":"get_equipment_health"}}]',
        )

    def test_contracts_are_frozen_tuple_typed_and_schema_validated(self) -> None:
        context = self.context()
        narrowed = context.for_tool_call("server-call", "step-1")
        self.assertEqual(
            (narrowed.run_id, narrowed.call_id, narrowed.step_id),
            ("run-1", "server-call", "step-1"),
        )
        self.assertIs(narrowed.principal, context.principal)
        self.assertIs(narrowed.limits, self.limits)
        self.assertIs(narrowed.cancellation, self.cancellation)
        self.assertIsNone(narrowed.dependencies)
        call = ModelToolCall("model-id", "get_equipment_health", "{not json")
        response = ModelResponse(
            "answer", (call,), ModelUsage(1, 2, 3), "provider-response"
        )
        message = ModelMessage("assistant", "answer", (call,))
        self.assertEqual(message.tool_calls, (call,))
        self.assertEqual(response.response_id, "provider-response")
        for value in (context, call, message, response):
            self.assertTrue(is_dataclass(value))
            self.assertTrue(type(value).__dataclass_params__.frozen)
        self.assertEqual(type(self.request().messages), tuple)
        for field in fields(RuntimeEvent):
            self.assertNotIn(
                field.name,
                {"content", "arguments", "data", "error", "exception", "secret"},
            )

        invalid: list[object] = [
            lambda: ModelUsage(True, 0, 0),
            lambda: ModelUsage(-1, 0, 0),
            lambda: ModelUsage(0, -1, 0),
            lambda: ModelUsage(0, 0, -1),
            lambda: ModelMessage("bad", "x"),
            lambda: ModelResponse(
                tool_calls=(
                    ModelToolCall("duplicate", "one", "{}"),
                    ModelToolCall("duplicate", "two", "{}"),
                )
            ),
            lambda: ModelToolCall("id", "x" * 129, "{}"),
            lambda: ModelMessage("tool", "result"),
            lambda: ModelMessage("assistant", "answer", tool_call_id="call"),
            lambda: ModelRequest("call", [], "[]"),
            lambda: ModelResponse(tool_calls=[]),
            lambda: ModelResponse(usage=object()),
            lambda: ModelRequest("call", (), "{}"),
            lambda: ModelRequest("call", (), '["not-an-object"]'),
            lambda: ModelRequest("call", (), "not-json"),
            lambda: ModelRequest("call", (), '[{"value":NaN}]'),
            lambda: ModelRequest("call", (), '[{"value":Infinity}]'),
            lambda: ModelRequest("call", (), '[{"value":1e999}]'),
            lambda: ModelRequest(
                "call", (), '[{"description":"' + "x" * 1_048_577 + '"}]'
            ),
            lambda: RuntimeEvent("run", "call", "model_response", ToolStatus.SUCCEEDED),
            lambda: RuntimeEvent(
                "run",
                "call",
                "model_response",
                ToolStatus.SUCCEEDED,
                usage=ModelUsage(),
                execution_state=ToolExecutionState.COMPLETED,
            ),
            lambda: RuntimeEvent(
                "run",
                "call",
                "tool_result",
                ToolStatus.SUCCEEDED,
                tool_name="tool",
                usage=ModelUsage(),
            ),
            lambda: RuntimeEvent(
                "run",
                "call",
                "tool_result",
                ToolStatus.SUCCEEDED,
                tool_name="tool",
                execution_state=None,
            ),
            lambda: RuntimeEvent(
                "run",
                "call",
                "tool_result",
                ToolStatus.SUCCEEDED,
                tool_name="tool",
                execution_state=ToolExecutionState.COMPLETED,
                schema_version="2.0.0",
            ),
        ]
        for factory in invalid:
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()
        self.assertEqual(ModelToolCall("id", "x" * 128, "{}").name, "x" * 128)

    def test_protocol_signatures_and_hints_are_explicit_async_contracts(self) -> None:
        for protocol, method, expected, expected_hints in (
            (
                ModelResponsePort,
                "complete",
                ("self", "request", "context"),
                {
                    "request": ModelRequest,
                    "context": RuntimeContext,
                    "return": ModelResponse,
                },
            ),
            (
                ToolDispatcherPort,
                "dispatch",
                ("self", "name", "raw_arguments", "context"),
                {
                    "name": str,
                    "raw_arguments": object,
                    "context": ToolExecutionContext[None],
                    "return": ToolResult[object],
                },
            ),
            (
                EventSink,
                "emit",
                ("self", "event"),
                {"event": RuntimeEvent, "return": type(None)},
            ),
        ):
            with self.subTest(protocol=protocol.__name__):
                signature = inspect.signature(getattr(protocol, method))
                self.assertEqual(tuple(signature.parameters), expected)
                hints = typing.get_type_hints(getattr(protocol, method))
                self.assertNotIn(typing.Any, hints.values())
                self.assertEqual(hints, expected_hints)
                self.assertTrue(
                    all(
                        parameter.annotation is not inspect.Parameter.empty
                        for name, parameter in signature.parameters.items()
                        if name != "self"
                    )
                )
                self.assertTrue(inspect.iscoroutinefunction(getattr(protocol, method)))
        expected_consumers = (
            (
                execute_model_stage,
                ("context", "request", "model"),
                "model",
                {
                    "context": RuntimeContext,
                    "request": ModelRequest,
                    "model": ModelResponsePort,
                    "return": StageResult[ModelResponse],
                },
            ),
            (
                execute_tool_stage,
                ("context", "call", "dispatcher", "call_id", "step_id"),
                "dispatcher",
                {
                    "context": RuntimeContext,
                    "call": ModelToolCall,
                    "dispatcher": ToolDispatcherPort,
                    "call_id": str,
                    "step_id": str | None,
                    "return": StageResult[ToolResult[object]],
                },
            ),
            (
                publish_stage_event,
                ("event", "sink"),
                "sink",
                {"event": RuntimeEvent, "sink": EventSink, "return": type(None)},
            ),
        )
        for function, names, keyword, expected_hints in expected_consumers:
            signature = inspect.signature(function)
            hints = typing.get_type_hints(function)
            self.assertEqual(tuple(signature.parameters), names)
            self.assertEqual(
                signature.parameters[keyword].kind, inspect.Parameter.KEYWORD_ONLY
            )
            self.assertTrue(
                all(
                    parameter.annotation is not inspect.Parameter.empty
                    for name, parameter in signature.parameters.items()
                    if name != "self"
                )
            )
            self.assertNotIn(typing.Any, hints.values())
            self.assertEqual(hints, expected_hints)

    async def test_model_stage_preserves_context_and_rejects_bad_port_value(
        self,
    ) -> None:
        context, request = self.context(), self.request()
        model = FakeModel(ModelResponse("ok", usage=ModelUsage(1, 1, 2)))
        stage = await execute_model_stage(context, request, model=model)
        self.assertEqual(model.calls, 1)
        self.assertIs(model.context, context)
        self.assertIs(stage.value, model.response)
        self.assertEqual(
            (stage.event.run_id, stage.event.call_id, stage.event.kind),
            ("run-1", "provider-call", "model_response"),
        )
        self.assertEqual(stage.event.status, ToolStatus.SUCCEEDED)
        self.assertEqual(stage.event.usage, ModelUsage(1, 1, 2))
        self.assertIsNone(stage.event.execution_state)
        secret_marker = "model-port-secret-marker"
        with self.assertRaises(RuntimeContractError) as raised:
            await execute_model_stage(context, request, model=FakeModel(secret_marker))
        self.assertNotIn(secret_marker, str(raised.exception))

    async def test_tool_stage_uses_server_call_id_and_preserves_result_identity(
        self,
    ) -> None:
        context = self.context()
        call = ModelToolCall("untrusted-model-call", "get_equipment_health", "{broken")
        result = ToolResult(
            "server-call",
            "get_equipment_health",
            "v1",
            ToolStatus.SUCCEEDED,
            ToolExecutionState.COMPLETED,
            [{"equipment_id": "EQ-1"}],
            row_count=1,
        )
        dispatcher = FakeDispatcher(result)
        stage = await execute_tool_stage(
            context,
            call,
            dispatcher=dispatcher,
            call_id="server-call",
            step_id="step-1",
        )
        self.assertEqual(dispatcher.calls, 1)
        assert dispatcher.seen is not None
        self.assertEqual(dispatcher.seen[:2], (call.name, call.arguments))
        narrow = dispatcher.seen[2]
        self.assertEqual((narrow.call_id, narrow.step_id), ("server-call", "step-1"))
        self.assertIs(narrow.principal, context.principal)
        self.assertIs(narrow.limits, self.limits)
        self.assertIs(narrow.cancellation, self.cancellation)
        self.assertIsNone(narrow.dependencies)
        self.assertIs(stage.value, result)
        self.assertEqual(
            (stage.event.call_id, stage.event.tool_name, stage.event.row_count),
            ("server-call", "get_equipment_health", 1),
        )
        self.assertEqual(stage.event.status, ToolStatus.SUCCEEDED)
        for bad in (
            "not-a-tool-result",
            ToolResult(
                "wrong",
                "get_equipment_health",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [],
            ),
            ToolResult(
                "server-call",
                "wrong",
                "v1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                [],
            ),
        ):
            with (
                self.subTest(bad=repr(bad)),
                self.assertRaises(RuntimeContractError),
            ):
                await execute_tool_stage(
                    context,
                    call,
                    dispatcher=FakeDispatcher(bad),  # type: ignore[arg-type]
                    call_id="server-call",
                )

        for status, state, error in (
            (
                ToolStatus.TIMED_OUT,
                ToolExecutionState.UNKNOWN,
                ToolError("TIMEOUT", "timed out", ToolErrorKind.TIMEOUT),
            ),
            (
                ToolStatus.CANCELLED,
                ToolExecutionState.NOT_STARTED,
                ToolError("CANCELLED", "cancelled", ToolErrorKind.CANCELLATION),
            ),
        ):
            with self.subTest(status=status):
                expected = ToolResult(
                    "server-call", call.name, "v1", status, state, error=error
                )
                stage = await execute_tool_stage(
                    context,
                    call,
                    dispatcher=FakeDispatcher(expected),
                    call_id="server-call",
                )
                self.assertIs(stage.value, expected)
                self.assertEqual(stage.event.execution_state, state)

    async def test_exceptions_cancellation_and_sink_failure_do_not_retry(self) -> None:
        context, request = self.context(), self.request()
        model = FakeModel(ModelResponse())
        sink = FakeSink(RuntimeError("sink unavailable"))
        stage = await execute_model_stage(context, request, model=model)
        with self.assertRaisesRegex(RuntimeError, "sink unavailable"):
            await publish_stage_event(stage.event, sink=sink)
        self.assertEqual(model.calls, 1)
        self.assertIs(stage.value, model.response)

        class CancelledModel:
            async def complete(
                self, request: ModelRequest, context: RuntimeContext
            ) -> ModelResponse:
                raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await execute_model_stage(context, request, model=CancelledModel())

        class BrokenModel:
            async def complete(
                self, request: ModelRequest, context: RuntimeContext
            ) -> ModelResponse:
                raise LookupError("provider is unavailable")

        with self.assertRaisesRegex(LookupError, "provider is unavailable"):
            await execute_model_stage(context, request, model=BrokenModel())

        entered = asyncio.Event()
        release = asyncio.Event()

        class WaitingModel:
            async def complete(
                self, request: ModelRequest, context: RuntimeContext
            ) -> ModelResponse:
                entered.set()
                await release.wait()
                return ModelResponse()

        task = asyncio.create_task(
            execute_model_stage(context, request, model=WaitingModel())
        )
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class RuntimeDispatcherIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dispatcher_binding_and_stages_execute_once(self) -> None:
        today = date(2026, 10, 24)
        registry = ToolRegistry()
        adapter = demo_fake_adapter(demo_tenant_id="tenant-a", as_of=today)
        registry.register_native(
            create_equipment_health_binding(
                adapter,
                today=lambda: today,
            )
        )
        guard = ToolLoopGuard(_plan())
        dispatcher = ToolDispatcher(
            run_id="run-1",
            registry=registry,
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}), frozenset({"analyst"}), "tenant-a"
            ),
            budget=LoopGuardToolBudget(guard),
            allowed_tools=frozenset({"get_equipment_health"}),
        )
        recording = RecordingDispatcher(dispatcher)
        context = RuntimeContext(
            Principal(), "run-1", ToolExecutionLimits(remaining_calls=1)
        )
        call = ModelToolCall("model-call", "get_equipment_health", "{}")
        model = FakeModel(ModelResponse(tool_calls=(call,)))
        model_stage = await execute_model_stage(
            context,
            ModelRequest("provider-call", (ModelMessage("user", "health"),)),
            model=model,
        )
        tool_stage = await execute_tool_stage(
            context,
            model_stage.value.tool_calls[0],
            dispatcher=recording,
            call_id="server-call",
        )
        sink = FakeSink()
        await publish_stage_event(model_stage.event, sink=sink)
        await publish_stage_event(tool_stage.event, sink=sink)
        self.assertEqual(model.calls, 1)
        self.assertEqual(len(sink.events), 2)
        self.assertIs(tool_stage.value, recording.result)
        assert recording.result is not None
        self.assertIs(tool_stage.value.data, recording.result.data)
        self.assertEqual(recording.calls, 1)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(len(guard.evidence_fingerprints), 1)
        self.assertEqual(tool_stage.value.status, ToolStatus.SUCCEEDED)
        self.assertEqual(tool_stage.value.sources[0].scope.tenant_id, "tenant-a")
        self.assertEqual(tool_stage.event.call_id, "server-call")

        failing_sink = FakeSink(RuntimeError("sink unavailable"))
        with self.assertRaisesRegex(RuntimeError, "sink unavailable"):
            await publish_stage_event(tool_stage.event, sink=failing_sink)
        self.assertIs(tool_stage.value, recording.result)
        self.assertEqual(recording.calls, 1)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(len(guard.evidence_fingerprints), 1)

        failed = ToolResult(
            "failed-call",
            "get_equipment_health",
            "v1",
            ToolStatus.BLOCKED,
            ToolExecutionState.NOT_STARTED,
            error=ToolError("BUDGET", "budget blocked", ToolErrorKind.BUDGET),
        )
        failed_stage = await execute_tool_stage(
            context,
            call,
            dispatcher=FakeDispatcher(failed),
            call_id="failed-call",
        )
        self.assertIs(failed_stage.value, failed)
        self.assertEqual(failed_stage.event.status, ToolStatus.BLOCKED)

    async def test_bad_arguments_sql_name_and_zero_budget_are_rejected_before_fetch(
        self,
    ) -> None:
        today = date(2026, 10, 24)
        adapter = demo_fake_adapter(demo_tenant_id="tenant-a", as_of=today)
        registry = ToolRegistry()
        registry.register_native(
            create_equipment_health_binding(adapter, today=lambda: today)
        )
        context = RuntimeContext(Principal(), "run-1")
        for name, arguments, calls, status in (
            ("get_equipment_health", "{", 1, ToolStatus.INVALID_ARGUMENTS),
            ("sql_query", "{}", 1, ToolStatus.DENIED),
            ("get_equipment_health", "{}", 0, ToolStatus.BLOCKED),
        ):
            with self.subTest(name=name, calls=calls):
                dispatcher = ToolDispatcher(
                    run_id="run-1",
                    registry=registry,
                    policy=DemoToolPolicy(
                        frozenset({"get_equipment_health"}),
                        frozenset({"analyst"}),
                        "tenant-a",
                    ),
                    budget=LoopGuardToolBudget(ToolLoopGuard(_plan(calls))),
                    allowed_tools=frozenset({"get_equipment_health"}),
                )
                before = len(adapter.calls)
                stage = await execute_tool_stage(
                    context,
                    ModelToolCall("model", name, arguments),
                    dispatcher=dispatcher,
                    call_id="server-call",
                )
                self.assertEqual(stage.value.status, status)
                self.assertEqual(len(adapter.calls), before)
                self.assertEqual(stage.event.status, status)


if __name__ == "__main__":
    unittest.main()
