"""MOD-012 acceptance: Runtime paths reach providers only through ModelGatewayPort."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.agent_runtime import service as agent
from app.agent_runtime.execution.agent_loop import AgentLoopContext, run_agent_loop
from app.core.settings import get_settings
from app.model_gateway import streaming
from app.model_gateway.gateway import (
    ClientModelSession,
    HttpModelGateway,
    ModelEndpoint,
    ModelGatewayPort,
    ModelSessionPort,
)
from app.model_gateway.streaming import (
    model_error_category,
    retryable_model_error,
    stream_completion,
)

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_CALLERS = (
    "app/agent_runtime/execution/agent_loop.py",
    "app/agent_runtime/stages/ready.py",
    "app/agent_runtime/synthesis/ready.py",
    "app/agent_runtime/preparation/context.py",
)
USAGE = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}


def _sse(*events: str) -> bytes:
    return "".join(f"data: {event}\n\n" for event in events).encode()


async def _silent_notify(_progress, _event) -> None:
    return None


async def _protocol_stream(client, url, headers, payload, progress, stream_state=None):
    return await stream_completion(
        client,
        url,
        headers,
        payload,
        progress,
        stream_state,
        notify=_silent_notify,
        disclosure_checker=lambda _text: True,
    )


def _forbidden_client(*_args, **_kwargs):
    raise AssertionError("Runtime paths must not construct httpx.AsyncClient")


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/chat/completions")
    return httpx.HTTPStatusError(
        "upstream", request=request, response=httpx.Response(status, request=request)
    )


class TrackingClientFactory:
    """Builds real AsyncClients over MockTransport and remembers them."""

    def __init__(self, handler):
        self.handler = handler
        self.clients: list[httpx.AsyncClient] = []
        self.timeouts: list[object] = []

    def __call__(self, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), **kwargs
        )
        self.clients.append(client)
        return client


class ScriptedSession:
    def __init__(self, gateway: "ScriptedGateway", endpoint: ModelEndpoint):
        self._gateway = gateway
        self._endpoint = endpoint

    @property
    def endpoint(self) -> ModelEndpoint:
        return self._endpoint

    async def stream(self, payload, progress, stream_state=None):
        self._gateway.requests.append(payload)
        step = self._gateway.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return await step(payload, progress, stream_state)
        return step


class ScriptedGateway:
    """In-memory ModelGatewayPort; it never creates a transport client."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.opened: list[tuple[ModelEndpoint, float]] = []
        self.closed = 0

    def endpoint_for(self, connection, *, chat_template=None) -> ModelEndpoint:
        return ModelEndpoint.from_connection(connection, chat_template=chat_template)

    @asynccontextmanager
    async def open(self, endpoint, *, timeout_seconds):
        self.opened.append((endpoint, timeout_seconds))
        try:
            yield ScriptedSession(self, endpoint)
        finally:
            self.closed += 1


def _answer(content: str = "OK 完成") -> tuple[dict, dict, str]:
    return {"role": "assistant", "content": content}, dict(USAGE), "response"


def _runtime_settings(**overrides):
    values = {
        "model_connection": SimpleNamespace(
            provider="test",
            api_key="test-key",
            base_url="https://example.test",
            model="test-model",
        ),
        "api_timeout_seconds": 5,
        "model_context_timeout_seconds": 5,
        "model_max_retries": 0,
        "model_retry_base_seconds": 0.0,
        "model_circuit_failure_threshold": 1,
        "model_circuit_cooldown_seconds": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class GatewayStaticAcceptanceTests(unittest.TestCase):
    def test_runtime_paths_do_not_create_provider_clients_or_endpoints(self):
        for relative in GATEWAY_CALLERS:
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("AsyncClient", source)
                self.assertNotIn("/chat/completions", source)
                self.assertNotIn("Bearer", source)
        loop_source = (ROOT / GATEWAY_CALLERS[0]).read_text(encoding="utf-8")
        self.assertNotIn("import httpx", loop_source)

    def test_streaming_protocol_no_longer_reads_chat_template_environment(self):
        source = inspect.getsource(streaming)
        self.assertNotIn("FAB_CHAT_TEMPLATE_COMPAT", source)
        self.assertNotIn("os.getenv", source)

    def test_port_protocols_are_satisfied_by_adapters(self):
        gateway = HttpModelGateway(stream_completion=_protocol_stream)
        self.assertIsInstance(gateway, ModelGatewayPort)
        self.assertIsInstance(ScriptedGateway([]), ModelGatewayPort)
        self.assertIsInstance(
            ClientModelSession(None, "u", {}, _protocol_stream), ModelSessionPort
        )
        self.assertIs(gateway.client_factory, httpx.AsyncClient)

    def test_endpoint_repr_hides_api_key_and_builds_chat_completions_request(self):
        endpoint = ModelEndpoint.from_connection(
            SimpleNamespace(
                provider="p",
                model="m",
                base_url="https://h.test/v1",
                api_key="secret-key",
            ),
        )
        self.assertNotIn("secret-key", repr(endpoint))
        self.assertEqual(
            endpoint.chat_completions_url, "https://h.test/v1/chat/completions"
        )
        self.assertEqual(
            endpoint.headers(),
            {"Authorization": "Bearer secret-key", "Content-Type": "application/json"},
        )

    def test_settings_load_chat_template_mode_from_environment(self):
        with patch.dict(os.environ, {"FAB_CHAT_TEMPLATE_COMPAT": " merge-system "}):
            self.assertEqual(get_settings().chat_template_compat, "merge-system")
        environment = {
            k: v for k, v in os.environ.items() if k != "FAB_CHAT_TEMPLATE_COMPAT"
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertIsNone(get_settings().chat_template_compat)


class HttpModelGatewayTests(unittest.IsolatedAsyncioTestCase):
    def _endpoint(self, chat_template=None) -> ModelEndpoint:
        return ModelEndpoint(
            "test", "m", "https://provider.invalid/v1", "secret-key", chat_template
        )

    async def test_session_posts_sse_request_and_closes_owned_client(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    '{"id":"resp-1","choices":[{"delta":{"content":"hello"}}]}',
                    '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"lookup","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}',
                    '{"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}',
                    "[DONE]",
                ),
                headers={"content-type": "text/event-stream"},
            )

        factory = TrackingClientFactory(handler)
        gateway = HttpModelGateway(
            client_factory=factory, stream_completion=_protocol_stream
        )
        state: dict = {}
        async with gateway.open(self._endpoint(), timeout_seconds=7) as session:
            assistant, usage, response_id = await session.stream(
                {"model": "m", "messages": [{"role": "user", "content": "q"}]},
                None,
                state,
            )
            self.assertFalse(factory.clients[0].is_closed)
        self.assertTrue(factory.clients[0].is_closed)
        self.assertEqual(factory.timeouts, [7])
        self.assertEqual(
            seen[0].url, httpx.URL("https://provider.invalid/v1/chat/completions")
        )
        self.assertEqual(seen[0].headers["authorization"], "Bearer secret-key")
        body = json.loads(seen[0].content)
        self.assertTrue(body["stream"])
        self.assertEqual(body["stream_options"], {"include_usage": True})
        self.assertEqual(assistant["content"], "hello")
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(usage["total_tokens"], 6)
        self.assertEqual(response_id, "resp-1")
        self.assertEqual(state["finish_reason"], "tool_calls")
        self.assertEqual(session.endpoint.model, "m")

    async def test_http_error_propagates_and_client_is_closed(self):
        factory = TrackingClientFactory(lambda _request: httpx.Response(503))
        gateway = HttpModelGateway(
            client_factory=factory, stream_completion=_protocol_stream
        )
        with self.assertRaises(httpx.HTTPStatusError) as raised:
            async with gateway.open(self._endpoint(), timeout_seconds=1) as session:
                await session.stream({"messages": []}, None, {})
        self.assertTrue(retryable_model_error(raised.exception))
        self.assertEqual(model_error_category(raised.exception), "upstream_5xx")
        self.assertTrue(factory.clients[0].is_closed)

    async def test_cancellation_mid_stream_propagates_and_client_is_closed(self):
        first_chunk_sent = asyncio.Event()
        never = asyncio.Event()

        async def body():
            yield _sse('{"choices":[{"delta":{"content":"partial"}}]}')
            first_chunk_sent.set()
            await never.wait()

        factory = TrackingClientFactory(
            lambda _request: httpx.Response(200, content=body())
        )
        gateway = HttpModelGateway(
            client_factory=factory, stream_completion=_protocol_stream
        )

        async def call():
            async with gateway.open(self._endpoint(), timeout_seconds=1) as session:
                await session.stream({"messages": []}, None, {})

        task = asyncio.create_task(call())
        await asyncio.wait_for(first_chunk_sent.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(factory.clients[0].is_closed)

    async def test_enabled_chat_template_flattens_system_messages_without_mutating_request(
        self,
    ):
        captured: list[dict] = []

        async def capture(_client, _url, _headers, payload, _progress, _state):
            captured.append(payload)
            return _answer()

        @asynccontextmanager
        async def client_factory(**_kwargs):
            yield object()

        gateway = HttpModelGateway(
            client_factory=client_factory, stream_completion=capture
        )
        request = {
            "model": "m",
            "messages": [
                {"role": "system", "content": "a"},
                {"role": "user", "content": "q"},
                {"role": "system", "content": "b"},
            ],
        }
        original = json.loads(json.dumps(request))
        async with gateway.open(
            self._endpoint("merge-system"), timeout_seconds=1
        ) as session:
            await session.stream(request, None, {})
        async with gateway.open(self._endpoint(None), timeout_seconds=1) as session:
            await session.stream(request, None, {})
        self.assertEqual(
            captured[0]["messages"],
            [
                {"role": "system", "content": "a\n\nb"},
                {"role": "user", "content": "q"},
            ],
        )
        self.assertIs(captured[1], request)
        self.assertEqual(request, original)

    async def test_streaming_protocol_ignores_chat_template_environment(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200, content=_sse('{"choices":[{"delta":{"content":"x"}}]}', "[DONE]")
            )

        messages = [
            {"role": "user", "content": "q"},
            {"role": "system", "content": "late"},
        ]
        with patch.dict(os.environ, {"FAB_CHAT_TEMPLATE_COMPAT": "merge-system"}):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                await _protocol_stream(
                    client,
                    "https://p.invalid/chat/completions",
                    {},
                    {"messages": messages},
                    None,
                    {},
                )
        self.assertEqual(bodies[0]["messages"], messages)

    async def test_legacy_client_session_passes_raw_arguments_without_shaping(self):
        calls: list[tuple] = []

        async def capture(*args):
            calls.append(args)
            return _answer()

        session = ClientModelSession("client", "raw-url", {"h": "1"}, capture)
        payload = {
            "messages": [
                {"role": "user", "content": "q"},
                {"role": "system", "content": "s"},
            ]
        }
        await session.stream(payload, "progress", {"s": 1})
        self.assertIsNone(session.endpoint)
        self.assertEqual(
            calls, [("client", "raw-url", {"h": "1"}, payload, "progress", {"s": 1})]
        )


class _Guard(SimpleNamespace):
    def reserve_final_iteration(self):
        return None


def _loop_context(
    gateway,
    *,
    settings=None,
    health_enabled=True,
    record_success=None,
    record_failure=None,
    events=None,
    offline_answer=None,
    messages=None,
):
    events = events if events is not None else []

    async def no_op(*_args):
        return None

    return AgentLoopContext(
        settings=settings or _runtime_settings(model_max_retries=1),
        connection=SimpleNamespace(
            provider="test", api_key="k", base_url="https://example.test", model="m"
        ),
        intent_route=SimpleNamespace(intent="conversation"),
        execution_plan=SimpleNamespace(status="unsupported", steps=()),
        selected_playbook=None,
        loop_guard=_Guard(
            max_model_iterations=2,
            total_calls=0,
            force_synthesis=False,
            stop_reason=None,
        ),
        run_id="run",
        progress=None,
        thinking=False,
        main_recovery_trial=False,
        health_enabled=health_enabled,
        selected_model_id="model-a",
        question="q",
        analysis_question="q",
        playbook_selection=None,
        context_resolution=SimpleNamespace(to_dict=dict),
        messages=messages
        if messages is not None
        else [{"role": "user", "content": "q"}],
        trace=[],
        sources={},
        evidence_observations=[],
        evidence_validation=SimpleNamespace(),
        answer_contract=SimpleNamespace(status="optional"),
        total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        knowledge_fallback={"used": False, "disclosure": None},
        fallback_announced=False,
        applied_synthesis_reason=None,
        health={"status": "healthy"},
        build_result=lambda answer, _report: {"answer": answer, "thinking_policy": {}},
        notify=no_op,
        stream_answer=no_op,
        emit_event=lambda name, _run_id, **fields: events.append((name, fields)),
        model_gateway=gateway,
        retryable_model_error=retryable_model_error,
        model_error_category=model_error_category,
        model_failure_reason=lambda exc: model_error_category(exc),
        model_retry_delay=lambda *_args: 0.0,
        record_model_success=record_success
        or (lambda _model: ({"status": "healthy"}, None)),
        record_model_failure=record_failure
        or (lambda *_a, **_k: ({"status": "degraded"}, None)),
        audit_assistant=lambda value: value,
        tools=[],
        submit_analysis_tool={"name": "submit_analysis"},
        parse_tool_arguments=lambda *_args: ({}, None),
        execute_tool=lambda *_args: None,
        usable_knowledge_result=lambda *_args: False,
        normalize_general_knowledge_answer=lambda answer: answer,
        has_knowledge_fallback_disclosure=lambda *_args: False,
        knowledge_fallback_state=lambda *_args: {"used": False, "disclosure": None},
        validate_evidence=lambda *_args: None,
        create_answer_contract=lambda *_a, **_k: None,
        validator_system_message=lambda *_args: "",
        synthesizer_system_message=lambda *_args: "",
        synthesize_legacy_answer=lambda answer, *_a, **_k: SimpleNamespace(
            answer=answer, report={}
        ),
        synthesize_submission=lambda *_a, **_k: None,
        emit_answer_synthesis=lambda *_args: None,
        emit_evidence_validation=lambda *_args: None,
        offline_answer=offline_answer
        or (lambda *_a, **_k: {"answer": "local", "tool_trace": []}),
        evidence_observation_type=object,
        provider_request_options=lambda *_args: {},
        request_synthesis_correction=None,
    )


class LoopGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._client_patch = patch.object(httpx, "AsyncClient", new=_forbidden_client)
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    async def test_loop_completes_through_injected_port_and_accumulates_usage(self):
        gateway = ScriptedGateway([_answer("循环完成")])
        context = _loop_context(gateway)
        result = await run_agent_loop(context)
        self.assertEqual(result["answer"], "循环完成")
        self.assertEqual(context.total_usage, USAGE)
        self.assertEqual(gateway.closed, 1)
        endpoint, timeout = gateway.opened[0]
        self.assertEqual(
            (endpoint.chat_completions_url, timeout),
            ("https://example.test/chat/completions", 5),
        )

    async def test_retryable_503_then_success_schedules_retry_and_records_success(self):
        events: list[tuple[str, dict]] = []
        successes: list[str] = []
        failures: list[tuple] = []

        def success(model_id):
            successes.append(model_id)
            return {"status": "healthy"}, "recovered"

        def failure(*args, **kwargs):
            failures.append((args, kwargs))
            return {"status": "degraded"}, None

        gateway = ScriptedGateway([_status_error(503), _answer()])
        context = _loop_context(
            gateway, events=events, record_success=success, record_failure=failure
        )
        result = await run_agent_loop(context)
        names = [name for name, _fields in events]
        self.assertEqual(result["answer"], "OK 完成")
        self.assertEqual(names.count("model_call_started"), 2)
        self.assertIn("model_call_retry_scheduled", names)
        self.assertIn("model_circuit_recovered", names)
        retry = next(
            fields for name, fields in events if name == "model_call_retry_scheduled"
        )
        self.assertEqual(
            (retry["attempt"], retry["next_attempt"], retry["error_type"]),
            (1, 2, "HTTPStatusError"),
        )
        self.assertEqual((successes, failures), (["model-a"], []))
        self.assertEqual((len(gateway.opened), gateway.closed), (1, 1))
        self.assertEqual(context.total_usage, USAGE)

    async def test_persistent_retryable_failure_records_health_and_falls_back(self):
        events: list[tuple[str, dict]] = []
        failures: list[tuple] = []

        def failure(*args, **kwargs):
            failures.append((args, kwargs))
            return {"status": "open"}, "opened"

        gateway = ScriptedGateway([_status_error(503), _status_error(503)])
        context = _loop_context(gateway, events=events, record_failure=failure)
        result = await run_agent_loop(context)
        names = [name for name, _fields in events]
        self.assertEqual(result["model"], "local-rules")
        self.assertEqual(
            result["model_health"]["fallback_reason"], "upstream_unavailable"
        )
        self.assertEqual(
            failures,
            [(("model-a", "upstream_5xx"), {"threshold": 1, "cooldown_seconds": 1})],
        )
        self.assertEqual(names.count("model_call_retry_scheduled"), 1)
        self.assertIn("model_health_failure_recorded", names)
        self.assertIn("model_local_fallback_activated", names)
        self.assertEqual(gateway.closed, 1)

    async def test_cancellation_propagates_closes_session_and_records_no_failure(self):
        events: list[tuple[str, dict]] = []
        failures: list[tuple] = []
        started = asyncio.Event()

        async def hang(_payload, _progress, _state):
            started.set()
            await asyncio.Event().wait()

        gateway = ScriptedGateway([hang])
        context = _loop_context(
            gateway,
            events=events,
            record_failure=lambda *a, **k: failures.append((a, k)) or ({}, None),
        )
        task = asyncio.create_task(run_agent_loop(context))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(gateway.closed, 1)
        self.assertEqual(failures, [])
        self.assertNotIn("model_health_failure_recorded", [name for name, _ in events])

    async def test_loop_passes_settings_chat_template_to_the_gateway_endpoint(self):
        captured: list[dict] = []

        async def capture(_client, _url, _headers, payload, _progress, _state):
            captured.append(payload)
            return _answer()

        @asynccontextmanager
        async def client_factory(**_kwargs):
            yield object()

        gateway = HttpModelGateway(
            client_factory=client_factory, stream_completion=capture
        )
        context = _loop_context(
            gateway,
            settings=_runtime_settings(chat_template_compat="merge-system"),
            messages=[
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "q"},
                {"role": "system", "content": "late"},
            ],
        )
        await run_agent_loop(context)
        roles = [item["role"] for item in captured[0]["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertEqual(captured[0]["messages"][0]["content"], "rules\n\nlate")


class ServiceEntryGatewayTests(unittest.TestCase):
    """The service entry builds one gateway per run from live namespace bindings."""

    def _run(self, question: str, gateway: ScriptedGateway, history=None) -> dict:
        with (
            patch(
                "app.agent_runtime.service.get_settings",
                return_value=_runtime_settings(),
            ),
            patch(
                "app.agent_runtime.service.HttpModelGateway",
                new=lambda **_kwargs: gateway,
            ),
            patch.object(httpx, "AsyncClient", new=_forbidden_client),
        ):
            return asyncio.run(
                agent._run_agent_impl(question, history or [], "mod-012-entry")
            )

    def test_loop_run_uses_injected_gateway_only(self):
        gateway = ScriptedGateway([_answer("工厂总览完成")])
        result = self._run("查看工厂总览", gateway)
        self.assertEqual(result["answer"], "工厂总览完成")
        self.assertEqual(result["usage"], USAGE)
        self.assertEqual((len(gateway.opened), gateway.closed), (1, 1))

    def test_ready_synthesis_uses_injected_gateway_only(self):
        gateway = ScriptedGateway([_answer("Ready 综合完成")])
        result = self._run("分析 CMP-03 最近7天 Cpk", gateway)
        self.assertEqual(result["execution_mode"], "deterministic_ready_plan")
        self.assertEqual(
            [tool["function"]["name"] for tool in gateway.requests[0]["tools"]],
            ["submit_analysis"],
        )
        self.assertEqual(result["usage"], USAGE)
        self.assertEqual((len(gateway.opened), gateway.closed), (1, 1))

    def test_context_resolution_uses_injected_gateway_only(self):
        content = json.dumps(
            {
                "relation": "followup",
                "resolved_question": "继续分析 CMP-03 的 Cpk",
                "topic_anchor": "CMP-03",
                "target_message_ids": [],
                "confidence": 0.95,
                "intent_hint": "manufacturing_analysis",
            },
            ensure_ascii=False,
        )
        gateway = ScriptedGateway(
            [({"role": "assistant", "content": content}, dict(USAGE), "ctx")]
        )
        history = [
            {"role": "user", "content": "分析 CMP-03 的 Cpk"},
            {"role": "assistant", "content": "已分析"},
        ]
        with (
            patch(
                "app.agent_runtime.service.HttpModelGateway",
                new=lambda **_kwargs: gateway,
            ),
            patch.object(httpx, "AsyncClient", new=_forbidden_client),
        ):
            resolution, usage = asyncio.run(
                agent._resolve_conversation_turn(
                    "继续",
                    history,
                    _runtime_settings(),
                    "mod-012-context",
                    None,
                    SimpleNamespace(intent="unknown"),
                )
            )
        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.resolved_question, "继续分析 CMP-03 的 Cpk")
        self.assertEqual(usage["total_tokens"], 5)
        self.assertEqual((len(gateway.opened), gateway.closed), (1, 1))
        self.assertEqual(gateway.opened[0][1], 5)

    def test_ready_session_facade_keeps_retry_policy_at_the_call_site(self):
        events: list[tuple[str, dict]] = []
        gateway = ScriptedGateway([_status_error(503), _answer()])
        connection = SimpleNamespace(
            provider="test", api_key="k", base_url="https://example.test", model="m"
        )

        async def run():
            async with gateway.open(
                gateway.endpoint_for(connection), timeout_seconds=1
            ) as session:
                return await agent._request_ready_synthesis_session(
                    session,
                    connection,
                    _runtime_settings(),
                    [],
                    "run",
                    False,
                    1,
                )

        with (
            patch(
                "app.agent_runtime.service.emit",
                new=lambda name, _run, **fields: events.append((name, fields)),
            ),
            patch("app.agent_runtime.service.asyncio.sleep", new=AsyncMock()),
        ):
            assistant, usage, _, _ = asyncio.run(run())
        retry = next(
            fields for name, fields in events if name == "model_call_retry_scheduled"
        )
        self.assertEqual(retry["phase"], "ready_plan_synthesis")
        self.assertEqual(assistant["content"], "OK 完成")
        self.assertEqual(usage, USAGE)
        self.assertEqual(gateway.closed, 1)


if __name__ == "__main__":
    unittest.main()
