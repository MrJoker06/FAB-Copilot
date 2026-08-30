"""Loopback-only deterministic OpenAI-compatible streaming and probe fixture."""
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
        parts = [part for part in self.path.split("?")[0].split("/") if part]
        requested = parts[-3] if len(parts) >= 4 and parts[-2:] == ["chat", "completions"] else ""
        scenario = requested.replace("-", "_") if requested in {"compatibility", "invalid-tool", "image-rejected", "upstream-unavailable"} else self.scenario
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            payload = {}
        if scenario in {"rate_limit", "server_error", "upstream_unavailable"}:
            self.send_response(429 if scenario == "rate_limit" else 500); self.end_headers(); return
        if scenario == "image_rejected" and any(isinstance(item.get("content"), list) for item in payload.get("messages", []) if isinstance(item, dict)):
            self.send_response(422); self.end_headers(); return
        self.send_response(200); self.send_header("content-type", "text/event-stream")
        if scenario == "partial_disconnect": self.send_header("content-length", "999")
        self.end_headers()
        if scenario == "timeout_before_body": time.sleep(0.2); return
        if scenario == "invalid_json": self.wfile.write(b"data: nope\n\n")
        elif scenario in {"compatibility", "image_rejected"} and payload.get("response_format"):
            content = json.dumps({"relation":"standalone","resolved_question":"probe","topic_anchor":"","target_message_ids":[],"confidence":1.0,"intent_hint":"unclear"})
            self.wfile.write(b"data: " + json.dumps({"id":"fixture","choices":[{"delta":{"content":content}}]}).encode() + b"\n\n")
        elif scenario in {"compatibility", "image_rejected", "invalid_tool"} and payload.get("tools") and not any(item.get("role") == "tool" for item in payload.get("messages", []) if isinstance(item, dict)):
            arguments = '{"ok":false}' if scenario == "invalid_tool" else '{"ok":true}'
            delta = {"tool_calls":[{"index":0,"id":"call-fixture","type":"function","function":{"name":"compatibility_probe","arguments":arguments}}]}
            if payload.get("reasoning_effort") or payload.get("thinking", {}).get("type") == "enabled": delta["reasoning_content"] = "fixture-thinking"
            self.wfile.write(b"data: " + json.dumps({"id":"fixture","choices":[{"delta":delta}]}).encode() + b"\n\n")
        elif scenario == "compatibility" and any(isinstance(item.get("content"), list) for item in payload.get("messages", []) if isinstance(item, dict)):
            self.wfile.write(b'data: {"id":"fixture","choices":[{"delta":{"content":"BLACK"}}]}\n\n')
        else: self.wfile.write(b'data: {"id":"fixture","choices":[{"delta":{"content":"ok"}}]}\n\n')
        self.wfile.flush()
        if scenario not in {"partial_disconnect", "missing_done", "invalid_json"}:
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()


class LocalOpenAIProtocolFixture:
    channel = CHANNEL
    def __init__(self, scenario: str = "ok", port: int = 0):
        self.scenario, self.port, self.server, self.thread = scenario, port, None, None
    def __enter__(self):
        handler = type("FixtureHandler", (_Handler,), {"scenario": self.scenario})
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        return self
    def __exit__(self, *_):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def scenario_base_url(self, scenario: str) -> str:
        """Select a bounded request-aware scenario without another listener."""
        if scenario not in {"compatibility", "invalid_tool", "image_rejected", "upstream_unavailable"}:
            raise ValueError("unsupported fixture scenario")
        return f"{self.base_url}/{scenario.replace('_', '-')}"


def fixture_report(scenario: str, status: str) -> dict:
    return {"schema_version": 1, "channel": CHANNEL, "scenario": scenario, "status": status}
