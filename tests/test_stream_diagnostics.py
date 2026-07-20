import asyncio
import json
import unittest

from pydantic import ValidationError

from app.agent import _stream_completion
from app.main import StreamTelemetryRequest


class _FakeResponse:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeClient:
    def __init__(self, lines):
        self.response = _FakeResponse(lines)

    def stream(self, *_args, **_kwargs):
        return self.response


class StreamDiagnosticsTest(unittest.TestCase):
    def test_model_stream_records_aggregate_timing_without_content(self):
        first = "第一段内容" * 8
        second = "第二段内容" * 8
        chunks = [
            {"id": "response-1", "choices": [{"delta": {"content": first}}]},
            {"choices": [{"delta": {"content": second}, "finish_reason": "stop"}]},
            {"usage": {"prompt_tokens": 10, "completion_tokens": 20}, "choices": []},
        ]
        lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks] + ["data: [DONE]"]
        state = {}
        events = []

        async def progress(event):
            events.append(event)

        assistant, usage, response_id = asyncio.run(
            _stream_completion(
                _FakeClient(lines), "https://model.invalid/chat", {}, {"messages": []}, progress, state
            )
        )

        self.assertEqual(assistant["content"], first + second)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(response_id, "response-1")
        self.assertEqual(state["content_delta_count"], 2)
        self.assertEqual(state["content_chars"], len(first + second))
        self.assertIn("first_content_ms", state)
        self.assertIn("max_content_gap_ms", state)
        self.assertNotIn(first, json.dumps(state, ensure_ascii=False))
        self.assertEqual("".join(event.get("delta", "") for event in events), first + second)

    def test_browser_telemetry_rejects_content_fields(self):
        with self.assertRaises(ValidationError):
            StreamTelemetryRequest(run_id="run-12345678", answer="回答正文")


if __name__ == "__main__":
    unittest.main()
