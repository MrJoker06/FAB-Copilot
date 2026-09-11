import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.model_gateway.compatibility import ModelCompatibilityError, check_model_compatibility, compatibility_limits, provider_request_options
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
            if body.get("response_format"):
                delta = {"content": '{"relation":"standalone","resolved_question":"介绍光刻基本原理","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}
            elif body.get("tools"):
                delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": '{\"ok\":true}'}}]}
            else:
                delta = {"content": "ok"}
            stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream; charset=utf-8"})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                report = await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
            self.assertEqual(report["status"], "passed")
            self.assertEqual([item["name"] for item in report["checks"]], ["connectivity_streaming", "tool_calls", "context_load", "structured_context", "limits"])
        asyncio.run(run())

    def test_tool_arguments_require_ok_true(self):
        for arguments in ("{}", '{"ok": false}'):
            def handler(request):
                body = json.loads(request.content)
                delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": arguments}}]} if body.get("tools") else {"content": "ok"}
                stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
                return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(ModelCompatibilityError) as raised:
                        await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
                self.assertEqual(raised.exception.category, "tool_arguments")
                self.assertEqual(raised.exception.summary, "模型未返回符合契约的 JSON 参数（要求 ok=true）")
            asyncio.run(run())

    def test_tool_call_requires_id_type_and_reassembles_fragments(self):
        def handler(request):
            body = json.loads(request.content)
            if body.get("response_format"):
                deltas = [{"content": '{"relation":"standalone","resolved_question":"介绍光刻基本原理","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}]
            elif body.get("tools"):
                deltas = [
                    {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_", "arguments": '{"'}}]},
                    {"tool_calls": [{"index": 0, "function": {"name": "probe", "arguments": 'ok":true}'}}]},
                ]
            else:
                deltas = [{"content": "ok"}]
            stream = "".join(f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\n" for delta in deltas) + "data: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                report = await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
            self.assertEqual(report["status"], "passed")
        asyncio.run(run())

        def missing_type_handler(request):
            body = json.loads(request.content)
            delta = {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "compatibility_probe", "arguments": '{"ok":true}'}}]} if body.get("tools") else {"content": "ok"}
            return httpx.Response(200, text=f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        async def reject_missing_type():
            async with httpx.AsyncClient(transport=httpx.MockTransport(missing_type_handler)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
            self.assertEqual(raised.exception.category, "tool_calls")
        asyncio.run(reject_missing_type())

    def test_structured_context_failure_is_categorized_without_response_leakage(self):
        secret = "response-secret-must-not-be-persisted"
        def handler(request):
            body = json.loads(request.content)
            if body.get("response_format"):
                delta = {"content": secret}
            elif body.get("tools"):
                delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": '{"ok":true}'}}]}
            else:
                delta = {"content": "ok"}
            return httpx.Response(200, text=f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client, context_chars=1024)
            self.assertEqual(raised.exception.category, "structured_context")
            self.assertNotIn(secret, raised.exception.summary)
        asyncio.run(run())

    def test_malformed_sse_is_rejected_and_provider_options_follow_contract(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="data: nope\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"}))) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True}, client=client)
            self.assertEqual(raised.exception.category, "malformed_sse")
        asyncio.run(run())
        self.assertEqual(provider_request_options("openai-compatible", False), {})
        self.assertEqual(provider_request_options("deepseek", False), {"thinking": {"type": "disabled"}})
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

    def test_deepseek_thinking_probes_are_isolated_and_keep_tool_contract(self):
        requests = []
        def handler(request):
            body = json.loads(request.content); requests.append(body)
            content = body["messages"][0]["content"]
            if body.get("response_format"):
                delta = {"content": '{"relation":"standalone","resolved_question":"介绍光刻基本原理","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}
            elif body.get("tools") and body["messages"][-1]["role"] == "tool":
                delta = {"content": "final", "reasoning_content": "continued thinking"}
            elif body.get("tools"):
                delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": '{"ok":true}'}}], "reasoning_content": "thinking"}
            elif isinstance(content, list):
                delta = {"content": "BLACK"}
            elif content == "Reply ok":
                delta = {"content": "ok", "reasoning_content": "thinking"}
            elif len(content) >= 1024:
                delta = {"reasoning_content": "thinking"} if body["thinking"] == {"type": "enabled"} else {"content": "ok"}
            else:
                delta = {"content": "ok"}
            stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        async def run():
            connection = SimpleNamespace(provider="deepseek", api_key="test-key", base_url="https://model.test/v1", model="test")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await check_model_compatibility(connection, {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": True}, client=client, context_chars=1024)
        asyncio.run(run())
        tool_request = next(item for item in requests if item.get("tools"))
        roundtrip_request = next(item for item in requests if item.get("tools") and item["messages"][-1]["role"] == "tool")
        thinking_request = next(item for item in requests if item["messages"][0]["content"] == "Reply ok")
        basic_request = next(item for item in requests if item["messages"][0]["content"] == "Reply exactly: ok")
        context_request = next(item for item in requests if isinstance(item["messages"][0]["content"], str) and len(item["messages"][0]["content"]) >= 1024)
        image_request = next(item for item in requests if isinstance(item["messages"][0]["content"], list))
        self.assertNotIn("tool_choice", tool_request)
        self.assertNotIn("tool_choice", roundtrip_request)
        self.assertEqual(tool_request["max_tokens"], 512)
        self.assertEqual(tool_request["thinking"], {"type": "enabled"})
        self.assertEqual(thinking_request["max_tokens"], 512)
        self.assertEqual(thinking_request["thinking"], {"type": "enabled"})
        self.assertEqual(basic_request["thinking"], {"type": "disabled"})
        self.assertEqual(context_request["thinking"], {"type": "disabled"})
        self.assertEqual(image_request["thinking"], {"type": "disabled"})
        structured_request = next(item for item in requests if item.get("response_format"))
        self.assertEqual(structured_request["response_format"], {"type": "json_object"})
        self.assertEqual(structured_request["max_tokens"], 1200)
        self.assertEqual(structured_request["thinking"], {"type": "disabled"})
        self.assertEqual(roundtrip_request["messages"][1]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(roundtrip_request["messages"][2]["tool_call_id"], "call-1")
        self.assertEqual(roundtrip_request["messages"][1]["reasoning_content"], "thinking")

    def test_deepseek_non_thinking_probes_explicitly_disable_thinking(self):
        requests = []
        def handler(request):
            body = json.loads(request.content); requests.append(body)
            if body.get("response_format"):
                deltas = [{"content": '{"relation":"standalone","resolved_question":"介绍光刻基本原理","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}]
            elif body.get("tools"):
                arguments = '{"ok":true}'
                deltas = [
                    {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": arguments[:2]}}]},
                    {"tool_calls": [{"index": 0, "function": {"arguments": arguments[2:]}}]},
                ]
            else:
                deltas = [{"content": "ok"}]
            stream = "".join(f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\n" for delta in deltas) + "data: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        async def run():
            connection = SimpleNamespace(provider="deepseek", api_key="test-key", base_url="https://model.test/v1", model="test")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await check_model_compatibility(connection, {"streaming": True, "tool_calls": True, "thinking": False}, client=client, context_chars=1024)
        asyncio.run(run())
        self.assertEqual(len(requests), 4)
        tool_requests = [item for item in requests if item.get("tools")]
        self.assertEqual(len(tool_requests), 1)
        self.assertEqual(tool_requests[0]["max_tokens"], 512)
        self.assertEqual(tool_requests[0]["tools"][0]["function"]["parameters"]["additionalProperties"], False)
        self.assertTrue(all(item["thinking"] == {"type": "disabled"} for item in requests))

    def test_multimodal_capability_failures_are_specific_and_safe(self):
        def is_image_request(body):
            return isinstance(body["messages"][0]["content"], list)

        def success_response(body):
            delta = ({"content": '{"relation":"standalone","resolved_question":"介绍光刻基本原理","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}
                     if body.get("response_format") else ({"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": '{"ok":true}'}}]}
                     if body.get("tools") else {"content": "ok"}))
            stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

        async def check_image_failure(outcome):
            def handler(request):
                body = json.loads(request.content)
                if is_image_request(body):
                    if outcome == "network":
                        raise httpx.ConnectError("offline", request=request)
                    return httpx.Response(outcome, headers={"content-type": "text/event-stream"})
                return success_response(body)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True, "native_multimodal": True}, client=client, context_chars=1024)
            return raised.exception

        rejected = asyncio.run(check_image_failure(400))
        self.assertEqual(rejected.category, "multimodal")
        self.assertEqual(rejected.summary, "模型不具备原生多模态能力（图片输入被模型拒绝）")
        self.assertFalse(rejected.retryable)
        self.assertEqual(rejected.http_status, 400)
        for outcome, category, retryable in ((401, "http", False), (429, "http", True), ("network", "network", True)):
            error = asyncio.run(check_image_failure(outcome))
            self.assertEqual(error.category, category)
            self.assertEqual(error.retryable, retryable)

    def test_multimodal_content_must_recognize_image(self):
        def handler(request):
            body = json.loads(request.content)
            if body.get("response_format"):
                delta = {"content": '{"relation":"standalone","resolved_question":"介绍光刻","topic_anchor":"","target_message_ids":[],"confidence":1,"intent_hint":"general_knowledge"}'}
            elif body.get("tools"):
                delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "compatibility_probe", "arguments": '{"ok":true}'}}]}
            elif isinstance(body["messages"][0]["content"], list):
                delta = {"content": "WHITE"}
            else:
                delta = {"content": "ok"}
            stream = f"data: {{\"choices\":[{{\"delta\":{json.dumps(delta)}}}]}}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ModelCompatibilityError) as raised:
                    await check_model_compatibility(self.connection(), {"streaming": True, "tool_calls": True, "native_multimodal": True}, client=client, context_chars=1024)
            self.assertEqual(raised.exception.category, "multimodal")
            self.assertEqual(raised.exception.summary, "模型不具备原生多模态能力（图片内容识别未通过）")
        asyncio.run(run())
