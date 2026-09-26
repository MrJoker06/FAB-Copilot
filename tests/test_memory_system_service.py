from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest

from app.agent_runtime.preparation.context import (
    ResolverDependencies,
    _resolve_with_memory_service,
)
from app.memory_system.context.resolver import (
    semantic_context_resolution,
    unresolved_context,
)
from app.memory_system.ports import ContextModelResult, ContextResolveRequest
from app.memory_system.service import ContextService


def _payload(question: str = "继续分析") -> dict:
    return {
        "relation": "followup",
        "resolved_question": f"{question}：补全历史条件",
        "topic_anchor": "历史问题",
        "target_message_ids": [],
        "confidence": 0.9,
        "intent_hint": "manufacturing_analysis",
    }


class FakeClock:
    def __init__(self, now: float = 0):
        self.now = now
        self.sleeps: list[float] = []
        self.perf_counter_calls = 0

    def perf_counter(self) -> float:
        self.perf_counter_calls += 1
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeEvents:
    def __init__(self):
        self.emitted: list[tuple[str, dict]] = []
        self.notifications: list[dict] = []

    def emit(self, event_type: str, _run_id: str, **fields) -> None:
        self.emitted.append((event_type, fields))

    async def notify(self, _progress, event: dict) -> None:
        self.notifications.append(event)


class FakePolicy:
    def failure_reason(self, error: Exception) -> str:
        return "retryable" if self.retryable(error) else "internal_error"

    def retryable(self, error: Exception) -> bool:
        return isinstance(error, OSError)

    def retry_delay(self, base_seconds: float, retry_number: int, _error: Exception) -> float:
        return base_seconds * retry_number

    def audit_assistant(self, assistant: dict | None) -> dict:
        return assistant or {}

    def fingerprint(self, content: str) -> str:
        return f"fp:{len(content)}"


class FakeModel:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[tuple[dict, float]] = []

    async def complete(self, payload: dict, timeout_seconds: float) -> ContextModelResult:
        self.calls.append((payload.copy(), timeout_seconds))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @asynccontextmanager
    async def open(self):
        yield self

    def timeout_error(self) -> Exception:
        return TimeoutError("deadline")


def _result(content: str, *, finish_reason: str = "stop", stream_state: dict | None = None) -> ContextModelResult:
    return ContextModelResult(
        {"content": content}, {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}, "response-1",
        stream_state if stream_state is not None else {"finish_reason": finish_reason},
    )


def _request(**overrides) -> ContextResolveRequest:
    values = dict(
        question="继续分析",
        history=[{"message_id": 1, "role": "user", "content": "先分析设备告警"}],
        model="test-model", provider_options=lambda: {}, timeout_seconds=10, retry_base_seconds=1,
        max_retries=1, run_id="run-1", thinking=False, eligible_for_model=True,
    )
    values.update(overrides)
    return ContextResolveRequest(**values)


class ContextServiceTests(unittest.IsolatedAsyncioTestCase):
    async def _service(self, results, *, clock=None, request=None):
        clock = clock or FakeClock()
        events = FakeEvents()
        model = FakeModel(results)
        service = ContextService(model=model, events=events, policy=FakePolicy(), clock=clock)
        resolution, usage = await service.resolve_turn(
            request or _request(), unresolved_context("继续分析"), object()
        )
        return resolution, usage, model, events, clock

    async def test_deterministic_and_ineligible_paths_do_not_open_model_or_notify(self):
        deterministic = unresolved_context("选第 1 点", "deterministic")
        deterministic = deterministic.__class__(
            **{**deterministic.__dict__, "applied": True}
        )
        events = FakeEvents()
        model = FakeModel([])
        service = ContextService(model=model, events=events, policy=FakePolicy(), clock=FakeClock())
        resolved, usage = await service.resolve_turn(_request(), deterministic, object())
        self.assertIs(resolved, deterministic)
        self.assertEqual(usage, {})
        self.assertEqual(model.calls, [])
        self.assertEqual(events.notifications, [])

        ineligible = _request(eligible_for_model=False)
        resolved, usage = await service.resolve_turn(ineligible, unresolved_context("继续分析"), object())
        self.assertFalse(resolved.applied)
        self.assertEqual(usage, {})
        self.assertEqual(model.calls, [])
        self.assertEqual(events.notifications, [])

    async def test_success_preserves_event_order_and_protocol_fingerprint(self):
        resolution, usage, model, events, _clock = await self._service([_result(__import__("json").dumps(_payload()))])
        self.assertTrue(resolution.applied)
        self.assertEqual(usage["total_tokens"], 7)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual([name for name, _fields in events.emitted], [
            "model_call_started", "model_call_finished", "question_context_classified",
        ])
        self.assertEqual(events.notifications[0]["message"], "正在结合当前会话理解这条消息")
        self.assertIn("context_resolution", events.notifications[-1])

    async def test_invalid_json_is_corrected_once_and_empty_length_expands_budget(self):
        valid = __import__("json").dumps(_payload())
        _resolution, _usage, model, events, _clock = await self._service([
            _result("not-json"), _result(valid),
        ])
        self.assertEqual(len(model.calls), 2)
        self.assertIn("未通过协议校验（invalid_json）", model.calls[1][0]["messages"][-1]["content"])
        self.assertEqual(events.emitted[1][1]["response_fingerprint"], "fp:8")

        _resolution, _usage, model, _events, _clock = await self._service([
            _result("", finish_reason="length"), _result(valid),
        ])
        self.assertEqual(model.calls[0][0]["max_tokens"], 1200)
        self.assertEqual(model.calls[1][0]["max_tokens"], 2400)

    async def test_mixed_protocol_transport_retries_share_deadline_and_recovery_does_not_retry(self):
        valid = __import__("json").dumps(_payload())
        _resolution, _usage, model, _events, clock = await self._service([
            _result("bad"), OSError("temporary"), _result(valid),
        ], request=_request(timeout_seconds=3, retry_base_seconds=1))
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(clock.sleeps, [1])

        _resolution, _usage, model, events, _clock = await self._service([
            _result("bad"), _result(valid),
        ], request=_request(health_recovery_trial=True))
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(events.emitted[-1][0], "question_context_resolution_failed")

    async def test_non_retryable_transport_failure_still_reads_remaining_budget_once(self):
        _resolution, _usage, model, events, clock = await self._service(
            [RuntimeError("permanent")]
        )
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(clock.perf_counter_calls, 6)
        self.assertEqual(
            [name for name, _fields in events.emitted],
            [
                "model_call_started",
                "model_call_finished",
                "question_context_resolution_failed",
            ],
        )
        self.assertFalse(events.emitted[1][1]["retryable"])
        self.assertFalse(events.emitted[1][1]["will_retry"])

    async def test_deadline_after_sleep_falls_back_and_retains_failed_stream_state(self):
        class OversleepingClock(FakeClock):
            async def sleep(self, seconds: float) -> None:
                await super().sleep(seconds)
                self.now += 1

        transient = OSError("temporary")
        transient.stream_state = {"finish_reason": "length", "reasoning_length": 11}
        _resolution, _usage, model, events, clock = await self._service(
            [transient], clock=OversleepingClock(), request=_request(timeout_seconds=1, retry_base_seconds=0.5)
        )
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(clock.sleeps, [0.5])
        finished = events.emitted[1][1]
        self.assertEqual(finished["finish_reason"], "length")
        self.assertEqual(finished["reasoning_length"], 11)
        self.assertEqual(events.emitted[-1][0], "question_context_resolution_failed")

    async def test_client_open_is_after_deadline_creation_and_can_exhaust_it(self):
        clock = FakeClock()

        class OpeningModel(FakeModel):
            @asynccontextmanager
            async def open(self):
                clock.now = 2
                yield self

        events = FakeEvents()
        model = OpeningModel([])
        service = ContextService(
            model=model,
            events=events,
            policy=FakePolicy(),
            clock=clock,
        )
        resolution, usage = await service.resolve_turn(
            _request(timeout_seconds=1),
            unresolved_context("继续分析"),
            object(),
        )
        self.assertEqual(usage, {})
        self.assertEqual(resolution.resolution_state, "unavailable")
        self.assertEqual(model.calls, [])
        self.assertEqual(
            [name for name, _fields in events.emitted],
            ["question_context_resolution_failed"],
        )


class ContextAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _dependencies(self, *, client_factory, stream_completion, notifications):
        async def notify(_progress, event):
            notifications.append(event)

        return ResolverDependencies(
            resolve_question_context=lambda question, _history: unresolved_context(question),
            unresolved_context=unresolved_context,
            build_messages=lambda *_args: [], response_format={}, provider_options=lambda *_args: {},
            stream_completion=stream_completion,
            semantic_resolution=semantic_context_resolution,
            notify=notify, emit=lambda *_args, **_kwargs: None, perf_counter=lambda: 0,
            async_client=client_factory, timeout=asyncio.timeout, sleep=asyncio.sleep,
            failure_reason=lambda _error: "internal_error", retryable_error=lambda error: isinstance(error, OSError),
            error_category=lambda _error: "network", retry_delay=lambda *_args: 0,
            audit_assistant=lambda assistant: assistant or {}, record_failure=lambda *_args, **_kwargs: ({}, None),
            record_success=lambda *_args, **_kwargs: ({}, None), content_fingerprint=lambda content: f"fp:{len(content)}",
        )

    async def test_no_history_skip_neither_opens_client_nor_notifies(self):
        opened = 0
        notifications: list[dict] = []
        def client_factory(**_kwargs):
            nonlocal opened
            opened += 1
            raise AssertionError("client should not open")
        deps = self._dependencies(client_factory=client_factory, stream_completion=None, notifications=notifications)
        settings = SimpleNamespace(model_connection=SimpleNamespace(api_key="key", model="m", base_url="http://unused", provider="openai"))
        settings.api_timeout_seconds = 1
        settings.model_context_timeout_seconds = 1
        settings.model_retry_base_seconds = 0
        settings.model_max_retries = 0
        settings.model_circuit_failure_threshold = 1
        settings.model_circuit_cooldown_seconds = 1
        resolved, usage = await _resolve_with_memory_service(
            "独立问题", None, settings, "run", object(), SimpleNamespace(intent="general_knowledge"), False, None, False, deps
        )
        self.assertEqual((resolved.original_question, usage, opened, notifications), ("独立问题", {}, 0, []))

    async def test_one_client_is_reused_for_protocol_retry_and_open_failure_escapes(self):
        opened = 0
        notifications: list[dict] = []
        client = object()

        class ClientContext:
            async def __aenter__(self):
                return client

            async def __aexit__(self, *_args):
                return False

        def client_factory(**_kwargs):
            nonlocal opened
            opened += 1
            return ClientContext()

        responses = [
            ({"content": "not-json"}, {}, None),
            ({"content": __import__("json").dumps(_payload())}, {}, None),
        ]

        async def stream_completion(actual_client, *_args):
            self.assertIs(actual_client, client)
            return responses.pop(0)

        deps = self._dependencies(
            client_factory=client_factory, stream_completion=stream_completion, notifications=notifications
        )
        settings = SimpleNamespace(model_connection=SimpleNamespace(api_key="key", model="m", base_url="http://unused", provider="openai"))
        settings.api_timeout_seconds = 1
        settings.model_context_timeout_seconds = 1
        settings.model_retry_base_seconds = 0
        settings.model_max_retries = 0
        settings.model_circuit_failure_threshold = 1
        settings.model_circuit_cooldown_seconds = 1
        resolved, _usage = await _resolve_with_memory_service(
            "继续分析", [{"message_id": 1, "role": "user", "content": "先分析"}], settings,
            "run", object(), SimpleNamespace(intent="unknown"), False, None, False, deps,
        )
        self.assertTrue(resolved.applied)
        self.assertEqual(opened, 1)

        def broken_client_factory(**_kwargs):
            raise RuntimeError("open failed")

        failed_notifications: list[dict] = []
        deps = self._dependencies(
            client_factory=broken_client_factory,
            stream_completion=stream_completion,
            notifications=failed_notifications,
        )
        with self.assertRaisesRegex(RuntimeError, "open failed"):
            await _resolve_with_memory_service(
                "继续分析", [{"message_id": 1, "role": "user", "content": "先分析"}], settings,
                "run", object(), SimpleNamespace(intent="unknown"), False, None, False, deps,
            )
        self.assertEqual(
            failed_notifications,
            [{"event": "stage", "stage": "context", "message": "正在结合当前会话理解这条消息"}],
        )

    async def test_adapter_uses_live_rule_and_provider_patch_points(self):
        notifications: list[dict] = []
        client = object()
        calls: list[str] = []

        class ClientContext:
            async def __aenter__(self):
                calls.append("open")
                return client

            async def __aexit__(self, *_args):
                return False

        async def stream_completion(actual_client, _endpoint, _headers, payload, *_args):
            self.assertIs(actual_client, client)
            self.assertEqual(payload["messages"], [{"role": "system", "content": "patched"}])
            self.assertEqual(payload["response_format"], {"type": "patched"})
            self.assertTrue(payload["provider_patch"])
            return {"content": __import__("json").dumps(_payload())}, {}, None

        deps = self._dependencies(
            client_factory=lambda **_kwargs: ClientContext(),
            stream_completion=stream_completion,
            notifications=notifications,
        )
        deps.build_messages = lambda *_args: [{"role": "system", "content": "patched"}]
        deps.response_format = {"type": "patched"}
        deps.provider_options = lambda *_args: {"provider_patch": True}

        def patched_semantic(question, _arguments, _history):
            calls.append("semantic")
            return unresolved_context(question)

        def patched_unresolved(question, source, *, failure_reason=""):
            calls.append(f"unresolved:{source}:{failure_reason}")
            return unresolved_context(question, source, failure_reason=failure_reason)

        deps.semantic_resolution = patched_semantic
        deps.unresolved_context = patched_unresolved
        settings = SimpleNamespace(
            model_connection=SimpleNamespace(
                api_key="key",
                model="m",
                base_url="http://unused",
                provider="openai",
            ),
            api_timeout_seconds=1,
            model_context_timeout_seconds=1,
            model_retry_base_seconds=0,
            model_max_retries=0,
            model_circuit_failure_threshold=1,
            model_circuit_cooldown_seconds=1,
        )
        await _resolve_with_memory_service(
            "继续分析",
            [{"message_id": 1, "role": "user", "content": "先分析"}],
            settings,
            "run",
            object(),
            SimpleNamespace(intent="unknown"),
            False,
            None,
            False,
            deps,
        )
        self.assertEqual(calls, ["open", "semantic"])

        async def invalid_completion(*_args):
            return {"content": "invalid"}, {}, None

        deps.stream_completion = invalid_completion
        await _resolve_with_memory_service(
            "继续分析",
            [{"message_id": 1, "role": "user", "content": "先分析"}],
            settings,
            "run",
            object(),
            SimpleNamespace(intent="unknown"),
            False,
            None,
            True,
            deps,
        )
        self.assertTrue(any(item.startswith("unresolved:fallback:") for item in calls))


if __name__ == "__main__":
    unittest.main()
