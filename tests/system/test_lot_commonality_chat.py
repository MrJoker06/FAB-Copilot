"""F4: chat runs reach lot commonality through its own route and carry analysis references."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.system.support import isolated_system_environment

isolated_system_environment()

import httpx  # noqa: E402

from scripts.local_openai_protocol_fixture import LocalOpenAIProtocolFixture  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "testserver"}
LOTS = ("L241226-00001", "L241226-00002", "L241226-00003")
TOOLS = {
    "create_lot_commonality_analysis",
    "read_lot_commonality_members",
    "read_lot_commonality_records",
}
VIEW_BYTES = 8 * 1024


def _stream_result(response):
    events = [json.loads(line) for line in response.text.splitlines() if line]
    return next(event["result"] for event in events if event.get("type") == "result")


class LotCommonalityChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original_send = httpx.AsyncClient.send

        async def loopback_only(client, request, *args, **kwargs):
            if request.url.host not in LOOPBACK:
                raise AssertionError(f"non-loopback request to {request.url.host}")
            return await original_send(client, request, *args, **kwargs)

        httpx.AsyncClient.send = loopback_only
        cls.addClassCleanup(setattr, httpx.AsyncClient, "send", original_send)
        cls.fixture = LocalOpenAIProtocolFixture()
        cls.fixture.__enter__()
        cls.addClassCleanup(cls.fixture.__exit__, None, None, None)
        base_url = cls.fixture.scenario_base_url("lot_commonality")
        scratch = Path(tempfile.mkdtemp(prefix="lca-chat-"))
        os.environ.update({
            "FAB_MODEL_BASE_URL": base_url,
            "DEEPSEEK_BASE_URL": base_url,
            "FAB_MODEL_API_KEY": "fixture-key",
            "DEEPSEEK_API_KEY": "fixture-key",
            "FAB_LOCAL_MODELS_PATH": str(scratch / "local_models.json"),
            "FAB_MODEL_CREDENTIALS_PATH": str(scratch / "model_credentials.json"),
        })
        from fastapi.testclient import TestClient

        from app.demo_data.database import db_session
        from app.main import app

        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)
        with db_session() as connection:
            connection.execute("UPDATE agent.model_catalog SET base_url = ?", (base_url,))
            connection.commit()

    def setUp(self):
        self.session = self.client.post("/api/sessions").json()["session_id"]
        self.fixture.requests.clear()

    def _tool_rounds(self):
        return [request for request in self.fixture.requests if request.get("tools")]

    def _create(self):
        question = f"分析 {'、'.join(LOTS)} 这几个 lot 的共性"
        response = self.client.post("/api/chat/stream", json={"message": question, "session_id": self.session})
        self.assertEqual(response.status_code, 200)
        return _stream_result(response)

    def test_chat_creates_an_analysis_with_only_the_commonality_tools(self):
        result = self._create()
        self.assertEqual(result["intent_route"]["intent"], "lot_commonality")
        trace = [(item["tool"], item["tool_status"]) for item in result["tool_trace"]]
        self.assertEqual(trace, [("create_lot_commonality_analysis", "succeeded")])
        self.assertEqual(len(result["analysis_refs"]), 1)
        reference = result["analysis_refs"][0]["analysis_ref"]
        self.assertEqual(result["analysis_refs"][0]["origin"], "created")
        self.assertIn(reference, result["answer"])

        rounds = self._tool_rounds()
        self.assertTrue(rounds)
        for request in rounds:
            names = {tool["function"]["name"] for tool in request["tools"]}
            self.assertLessEqual(TOOLS, names)
            self.assertFalse(names - TOOLS - {"submit_analysis"}, names)
        tool_message = next(
            message["content"]
            for message in rounds[-1]["messages"]
            if message.get("role") == "tool"
        )
        self.assertLess(len(tool_message.encode("utf-8")), VIEW_BYTES)
        view = json.loads(tool_message)["data"]
        self.assertEqual(view["analysis_ref"], reference)
        self.assertIn("omitted_candidates", view)

        page = self.client.get(f"/api/lot-commonality/analyses/{reference}")
        self.assertEqual(page.status_code, 200)
        self.assertEqual([lot["lot_id"] for lot in page.json()["groups"][0]["lot_states"]], list(LOTS))
        history = self.client.get(f"/api/sessions/{self.session}").json()["messages"]
        assistant = [message for message in history if message["role"] == "assistant"][-1]
        self.assertIn(reference, json.dumps(assistant, ensure_ascii=False))

    def test_attached_reference_is_reauthorized_and_read_by_reference(self):
        reference = self._create()["analysis_refs"][0]["analysis_ref"]
        self.fixture.requests.clear()
        response = self.client.post(
            "/api/chat",
            json={"message": "请解读这次结果，哪些候选值得优先排查？", "session_id": self.session, "analysis_ref": reference},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["intent_route"]["intent"], "lot_commonality")
        self.assertEqual(result["analysis_refs"][0], {"analysis_ref": reference, "origin": "attached"})
        read = result["tool_trace"][0]
        self.assertEqual((read["tool"], read["tool_status"]), ("read_lot_commonality_members", "succeeded"))
        self.assertEqual(read["arguments"]["analysis_ref"], reference)
        prompt = next(
            message["content"]
            for message in self._tool_rounds()[0]["messages"]
            if message.get("role") == "user" and "analysis_ref=" in str(message.get("content"))
        )
        self.assertIn(f"analysis_ref={reference}", prompt)
        messages = self.client.get(f"/api/sessions/{self.session}").json()["messages"]
        attached = [message for message in messages if message["role"] == "user"][-1]
        self.assertEqual(attached["content"], "请解读这次结果，哪些候选值得优先排查？")
        self.assertEqual(attached["metadata"], {"analysis_ref": reference})

    def test_catalog_policy_controls_chat_tools_and_reference_attachments(self):
        from app.bootstrap import capability_catalog as catalog

        with tempfile.TemporaryDirectory() as root, patch.object(
            catalog, "db_path", return_value=Path(root) / "capabilities.db"
        ):
            name = "create_lot_commonality_analysis"
            self.assertIn(
                name, {entry["name"] for entry in self.client.get("/api/capabilities").json()["items"]}
            )
            reference = self._create()["analysis_refs"][0]["analysis_ref"]
            catalog.save("tool", name, {"access": {"owner": "Litho", "readers": []},
                                        "groups": [], "enabled": True})
            self.assertNotIn(
                name, {entry["name"] for entry in self.client.get("/api/capabilities").json()["items"]}
            )
            self.fixture.requests.clear()
            blocked = self._create()
            self.assertEqual(blocked.get("analysis_refs", []), [])
            self.assertFalse(any(
                call["tool"] == name and call["tool_status"] == "succeeded"
                for call in blocked["tool_trace"]
            ))
            for request in self._tool_rounds():
                self.assertNotIn(name, {tool["function"]["name"] for tool in request["tools"]})
            before = self.client.get(f"/api/sessions/{self.session}").json()["messages"]
            self.fixture.requests.clear()
            for path in ("/api/chat", "/api/chat/stream"):
                response = self.client.post(path, json={
                    "message": "请解读这次共性分析", "session_id": self.session,
                    "analysis_ref": reference,
                })
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.json()["error_code"], "CAPABILITY_DENIED")
            self.assertFalse(self.fixture.requests)
            self.assertEqual(self.client.get(f"/api/sessions/{self.session}").json()["messages"], before)

    def test_unusable_references_are_rejected_before_anything_is_stored(self):
        reference = self._create()["analysis_refs"][0]["analysis_ref"]
        before = self.client.get(f"/api/sessions/{self.session}").json()["messages"]
        self.fixture.requests.clear()
        cases = (
            ({"x-user-id": "someone-else"}, reference, 404),
            ({}, "lca_" + "0" * 32, 404),
        )
        for headers, ref, status in cases:
            for path in ("/api/chat", "/api/chat/stream"):
                with self.subTest(path=path, ref=ref, headers=headers):
                    response = self.client.post(
                        path,
                        json={"message": "请解读这次共性分析", "session_id": self.session, "analysis_ref": ref},
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertEqual(response.json()["error_code"], "RESULT_UNAVAILABLE")
                    self.assertNotIn(ref, response.json()["detail"])
        combined = self.client.post(
            "/api/chat",
            json={"message": "x", "session_id": self.session, "analysis_ref": reference, "tool_result_ref": "tr_" + "0" * 32},
        )
        self.assertEqual(combined.status_code, 422)
        self.assertEqual(self.fixture.requests, [])
        after = self.client.get(f"/api/sessions/{self.session}").json()["messages"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
