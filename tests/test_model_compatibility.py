import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.model_compatibility import ModelCompatibilityError, check_model_compatibility, compatibility_limits, provider_request_options
from app.agent import _audit_assistant, _stream_completion


class ModelCompatibilityTests(unittest.TestCase):
    def connection(self):
        return SimpleNamespace(provider="openai-compatible", api_key="test-key", base_url="https://model.test/v1", model="test")

    def test_declared_required_capabilities_fail_without_network(self):
        async def run():
            with self.assertRaises(ModelCompatibilityError) as raised:
                await check_model_compatibility(self.connection(), {"streaming": False, "tool_calls": True})
            self.assertEqual(raised.exception.category, "required_capability")
        asyncio.run(run())

    def test_success_requires_sse_tool_json_and_context(self):
        def handler(request):
            body = json.loads(request.content)
            if body.get("tools"):
                delta = {"tool_calls": [{"index": 0, "function": {"name": "compatibility_probe", "arguments": '{\"ok\":true}'}}]}
            else:
                delta = {"content": "ok"}
            stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream; charset=utf-8"})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                report = await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(len(report["checks"]), 4)
        asyncio.run(run())

    def test_malformed_sse_is_rejected_and_options_do_not_disable_thinking(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="data: nope\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"}))) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client)
            self.assertEqual(raised.exception.category, "malformed_sse")
        asyncio.run(run())
        self.assertEqual(provider_request_options("openai-compatible", False), {})
        self.assertEqual(provider_request_options("deepseek", True)["thinking"], {"type": "enabled"})

    def test_missing_key_http_and_configuration_fail_safely(self):
        calls = 0
        def handler(request):
            nonlocal calls; calls += 1
            return httpx.Response(429, headers={"content-type": "text/event-stream"})
        async def run():
            missing = SimpleNamespace(**{**self.connection().__dict__, "api_key": ""})
            with self.assertRaises(ModelCompatibilityError) as raised: await check_model_compatibility(missing, {"streaming": True, "tool_calls": True})
            self.assertEqual(raised.exception.category, "missing_key")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised: await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client)
            self.assertTrue(raised.exception.retryable); self.assertEqual(calls, 1)
        asyncio.run(run())
        with self.assertRaises(ModelCompatibilityError) as raised:
            with patch.dict("os.environ", {"MODEL_COMPATIBILITY_CONTEXT_CHARS": "bad"}): compatibility_limits(None, None)
        self.assertEqual(raised.exception.category, "configuration")

    def test_protocol_missing_done_wrong_type_and_optional_probe_count(self):
        async def check(response):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised: await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client)
            return raised.exception.category
        self.assertEqual(asyncio.run(check(httpx.Response(200, text="data: {}\n\n", headers={"content-type":"text/event-stream"}))), "protocol")
        self.assertEqual(asyncio.run(check(httpx.Response(200, text="data: [DONE]\n\n"))), "content_type")

    def test_stream_completion_keeps_tool_reasoning_but_audit_strips_copy(self):
        async def run():
            stream = 'data: {"choices":[{"delta":{"reasoning_content":"hidden","tool_calls":[{"index":0,"function":{"name":"x","arguments":"{}"}}]}}]}\n\ndata: [DONE]\n\n'
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))) as client:
                assistant, _, _ = await _stream_completion(client, "https://model.test/v1/chat/completions", {}, {"model":"x","messages":[]}, None)
            return assistant
        assistant = asyncio.run(run())
        self.assertEqual(assistant["reasoning_content"], "hidden")
        audit = _audit_assistant(assistant)
        self.assertNotIn("reasoning_content", audit); self.assertIn("reasoning_content", assistant); self.assertIsNot(audit, assistant)
