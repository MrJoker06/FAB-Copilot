"""Offline acceptance tests for the portable model transport source unit."""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from app.model_gateway.gateway import HttpModelGateway, ModelEndpoint
from app.model_gateway.streaming import (
    audit_assistant,
    model_error_category,
    retryable_model_error,
    stream_completion,
)


def _sse(*events: str) -> bytes:
    return "".join(f"data: {event}\n\n" for event in events).encode()


class ModelTransportPortableTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_text_and_tool_calls_are_assembled_without_network(self):
        body = _sse(
            '{"id":"resp-1","choices":[{"delta":{"content":"hello "}}]}',
            '{"choices":[{"delta":{"content":"world"}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"lookup","arguments":"{\\\"lot\\\":\\\"A"}}]}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1\\\"}"}}]},"finish_reason":"tool_calls"}]}',
            '{"usage":{"total_tokens":7}}',
            "[DONE]",
        )

        async def notify(_progress, _event):
            return None

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url, httpx.URL("https://provider.invalid/v1/chat/completions"))
            self.assertTrue(request.content)
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assistant, usage, response_id = await stream_completion(
                client,
                "https://provider.invalid/v1/chat/completions",
                {},
                {"model": "offline", "messages": []},
                None,
                notify=notify,
                disclosure_checker=lambda _text: True,
            )

        self.assertEqual(assistant["content"], "hello world")
        self.assertEqual(assistant["tool_calls"], [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": '{"lot":"A1"}'}}])
        self.assertEqual(usage, {"total_tokens": 7})
        self.assertEqual(response_id, "resp-1")

    async def test_stream_without_done_is_not_accepted(self):
        async def notify(_progress, _event):
            return None

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=_sse('{"choices":[{"delta":{"content":"partial"}}]}')))
        ) as client:
            with self.assertRaisesRegex(ValueError, "final \\[DONE\\]"):
                await stream_completion(
                    client, "https://provider.invalid/stream", {}, {"messages": []}, None,
                    notify=notify, disclosure_checker=lambda _text: True,
                )

    async def test_gateway_owns_client_lifecycle_and_endpoint_headers(self):
        requests: list[httpx.Request] = []
        clients: list[httpx.AsyncClient] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=_sse(
                '{"choices":[{"delta":{"content":"ok"}}]}', '{"usage":{"total_tokens":2}}', "[DONE]",
            ))

        def client_factory(**kwargs):
            clients.append(httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
            return clients[-1]

        async def notify(_progress, _event):
            return None

        async def protocol(client, url, headers, payload, progress, state=None):
            return await stream_completion(
                client, url, headers, payload, progress, state,
                notify=notify, disclosure_checker=lambda _text: True,
            )

        gateway = HttpModelGateway(client_factory=client_factory, stream_completion=protocol)
        endpoint = ModelEndpoint("p", "offline", "https://provider.invalid/v1", "offline-key", "merge-system")
        self.assertNotIn("offline-key", repr(endpoint))
        async with gateway.open(endpoint, timeout_seconds=3) as session:
            assistant, usage, _ = await session.stream({"model": "offline", "messages": [
                {"role": "user", "content": "q"}, {"role": "system", "content": "late"},
            ]}, None, {})
        self.assertTrue(clients[0].is_closed)
        self.assertEqual(requests[0].url, httpx.URL("https://provider.invalid/v1/chat/completions"))
        self.assertEqual(requests[0].headers["authorization"], "Bearer offline-key")
        self.assertEqual(
            [item["role"] for item in json.loads(requests[0].content)["messages"]],
            ["system", "user"],
        )
        self.assertEqual((assistant["content"], usage), ("ok", {"total_tokens": 2}))

    async def test_reasoning_is_redacted_from_audit_record(self):
        self.assertEqual(
            audit_assistant({"content": "answer", "reasoning_content": "private trace"}),
            {"content": "answer"},
        )

    async def test_retry_classification_is_offline_and_explicit(self):
        request = httpx.Request("POST", "https://provider.invalid/stream")
        rate_limited = httpx.HTTPStatusError("rate limited", request=request, response=httpx.Response(429, request=request))
        server_error = httpx.HTTPStatusError("server", request=request, response=httpx.Response(503, request=request))
        invalid_request = httpx.HTTPStatusError("bad", request=request, response=httpx.Response(400, request=request))
        timeout = httpx.ReadTimeout("timeout", request=request)
        self.assertTrue(retryable_model_error(rate_limited))
        self.assertTrue(retryable_model_error(server_error))
        self.assertFalse(retryable_model_error(invalid_request))
        self.assertTrue(retryable_model_error(timeout))
        self.assertEqual(model_error_category(rate_limited), "rate_limit")
        self.assertEqual(model_error_category(timeout), "timeout")


if __name__ == "__main__":
    unittest.main()
