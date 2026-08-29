"""Loopback-only deterministic OpenAI-compatible streaming fault fixture."""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

CHANNEL = "LOCAL_PROTOCOL_FIXTURE"


class _Handler(BaseHTTPRequestHandler):
    scenario = "ok"
    def log_message(self, *_args): pass
    def do_POST(self):
        scenario = self.scenario
        if scenario in {"rate_limit", "server_error"}:
            self.send_response(429 if scenario == "rate_limit" else 500); self.end_headers(); return
        self.send_response(200); self.send_header("content-type", "text/event-stream")
        if scenario == "partial_disconnect": self.send_header("content-length", "999")
        self.end_headers()
        if scenario == "timeout_before_body": time.sleep(0.2); return
        if scenario == "invalid_json": self.wfile.write(b"data: nope\n\n")
        else: self.wfile.write(b'data: {"id":"fixture","choices":[{"delta":{"content":"ok"}}]}\n\n')
        self.wfile.flush()
        if scenario not in {"partial_disconnect", "missing_done", "invalid_json"}:
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()


class LocalOpenAIProtocolFixture:
    channel = CHANNEL
    def __init__(self, scenario: str = "ok"):
        self.scenario, self.server, self.thread = scenario, None, None
    def __enter__(self):
        handler = type("FixtureHandler", (_Handler,), {"scenario": self.scenario})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        return self
    def __exit__(self, *_):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"


def fixture_report(scenario: str, status: str) -> dict:
    return {"schema_version": 1, "channel": CHANNEL, "scenario": scenario, "status": status}
