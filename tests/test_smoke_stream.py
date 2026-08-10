from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import httpx

from scripts import smoke_stream


class FakeResponse:
    def __init__(self, lines, error=None):
        self.lines = lines
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_lines(self):
        return iter(self.lines)


def transport_for(response):
    @contextmanager
    def transport(*_args, **_kwargs):
        yield response

    return transport


class SmokeStreamTests(unittest.TestCase):
    def test_success_allows_blank_lines_and_uses_default_local_port(self):
        response = FakeResponse([
            "",
            json.dumps({"type": "session", "session_id": "session-1"}),
            json.dumps({"event": "run_started", "run_id": "run-1"}),
            json.dumps({"event": "tool_started"}),
            json.dumps({"event": "answer_delta"}),
            json.dumps({"type": "result"}),
        ])
        summary, errors = smoke_stream.run_smoke("q", smoke_stream.DEFAULT_URL, transport_for(response))
        self.assertEqual(smoke_stream.DEFAULT_URL, "http://127.0.0.1:8888/api/chat/stream")
        self.assertEqual(summary["session_id"], "session-1")
        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(errors, [])

    def test_parser_rejects_malformed_events_and_validation_reports_ordering(self):
        with self.assertRaisesRegex(ValueError, "Invalid NDJSON event at index 1"):
            smoke_stream.summarize_events(["not-json"])
        summary = smoke_stream.summarize_events([
            json.dumps({"event": "answer_delta"}),
            json.dumps({"event": "tool_finished"}),
        ])
        self.assertEqual(
            smoke_stream.validation_errors(summary),
            [
                "result event was not received",
                "tool event appeared after the first answer_delta event",
            ],
        )

    def test_main_returns_failure_for_stream_failures_without_network(self):
        cases = [
            (FakeResponse([json.dumps({"event": "answer_delta"})]), "result event was not received"),
            (FakeResponse([json.dumps({"type": "result"})]), "answer_delta event was not received"),
            (FakeResponse([], error=httpx.HTTPStatusError("bad status", request=None, response=None)), "HTTP request failed"),
            (FakeResponse([], error=ValueError("token=secret")), "Invalid NDJSON stream"),
        ]
        for response, expected in cases:
            replacement = (
                patch.object(smoke_stream, "run_smoke", return_value=({}, [expected]))
                if response.error is None
                else patch.object(smoke_stream, "run_smoke", side_effect=response.error)
            )
            with self.subTest(expected=expected), replacement, patch("builtins.print") as output:
                self.assertEqual(smoke_stream.main([]), 1)
            self.assertIn(expected, output.call_args_list[-1].args[0])
            self.assertNotIn("secret", output.call_args_list[-1].args[0])

    def test_main_returns_success_with_injected_transport_result(self):
        with patch.object(smoke_stream, "run_smoke", return_value=({"result_received": True}, [])), patch("builtins.print") as output:
            self.assertEqual(smoke_stream.main(["question"]), 0)
        self.assertEqual(json.loads(output.call_args.args[0]), {"result_received": True})


if __name__ == "__main__":
    unittest.main()
