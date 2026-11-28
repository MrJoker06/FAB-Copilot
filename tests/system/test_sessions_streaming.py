from __future__ import annotations

import json
import os
import unittest
from datetime import date
from unittest.mock import patch

import httpx

from tests.system.support import isolated_system_environment

isolated_system_environment()

from fastapi.testclient import TestClient

import app.main as main
from app.conversation.sessions import append_message, record_agent_result
from app.demo_data.database import db_session
from app.demo_data.seed import seed_reference_data
from app.main import app
from app.persistence.execution_store import (
    persist_execution_plan,
    recover_interrupted_executions,
    start_run_record,
    start_tool_event,
)
from app.telemetry.audit import read_events
from scripts.evaluate_trace_replay import load_dataset as load_trace_replay_dataset
from scripts.evaluate_trace_replay import replay_case


class SessionsStreamingSystemTests(unittest.TestCase):
    def test_concept_route_axes_survive_real_stream_and_session_reload_without_business_queries(self):
        from unittest.mock import AsyncMock

        from tests import test_tool_dispatcher as tool_fixture
        from tests.test_context_resolver import _settings
        from tests.test_default_native_runtime import DefaultNativeRuntimeTests

        model = AsyncMock(return_value=({"role": "assistant", "content": "Cpk 是比较过程波动与规格范围的统计指标。概念说明不代表某台设备当前的实际状态。"}, {}, "offline"))
        principal = tool_fixture.DispatcherTests().context().principal
        with (
            patch("app.main._validate_chat_model_capabilities", return_value=(principal, "offline")),
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", model),
            patch("app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port", new=DefaultNativeRuntimeTests._knowledge_port),
            TestClient(app) as client,
        ):
            session = client.post("/api/sessions").json()["session_id"]
            try:
                response = client.post("/api/chat/stream", json={"message": "什么是 Cpk？", "session_id": session})
                events = [json.loads(line) for line in response.text.splitlines() if line]
                result = next(item["result"] for item in events if item.get("type") == "result")
                route = result["intent_route"]
                self.assertEqual((route["intent"], route["request_type"]), ("general_knowledge", "explanation"))
                self.assertIn("capability", route["business_topics"])
                self.assertFalse(route["clarification_needed"])
                self.assertIn("Cpk", result["answer"])
                self.assertTrue(all(item["tool"] == "search_knowledge" for item in result["tool_trace"]))
                self.assertTrue(model.await_count)
                for call in model.await_args_list:
                    payload = call.args[3]
                    names = {item["function"]["name"] for item in payload.get("tools", [])}
                    self.assertTrue(names <= {"search_knowledge", "submit_analysis"}, names)
                saved = client.get(f"/api/sessions/{session}").json()["messages"][-1]["metadata"]
                self.assertEqual(saved["intent_route"], route)
            finally:
                client.delete(f"/api/sessions/{session}/permanent")

    def test_duty_skill_sync_stream_and_revoke_use_actual_dispatch(self):
        from dataclasses import replace
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.bootstrap import capability_catalog
        from app.core.settings import get_settings

        skill_id = "litho-cpk-diagnostic"
        name = "get_capability_trend"
        principal_headers = {"Authorization": "Bearer skill-fixture"}
        settings = get_settings()

        def register(client, kind, key, enabled=True, access=None):
            response = client.put(
                f"/api/admin/capabilities/{kind}/{key}",
                json={"access": access, "enabled": enabled, "groups": []},
                headers=principal_headers,
            )
            self.assertEqual(response.status_code, 200, response.text)

        def result(response):
            self.assertEqual(response.status_code, 200, response.text)
            if response.headers["content-type"].startswith("application/json"):
                return response.json()
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertFalse([item for item in events if item.get("type") == "error"], events)
            return next(item["result"] for item in events if item.get("type") == "result")

        def offline_settings(_):
            return replace(settings, model_connection=replace(settings.model_connection, api_key=""))

        with (
            TemporaryDirectory() as directory,
            patch.object(capability_catalog, "db_path", return_value=Path(directory) / "catalog.db"),
            patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": "skill-fixture"}),
            patch("app.agent_runtime.service.effective_agent_settings", side_effect=offline_settings),
            TestClient(app) as client,
        ):
            register(client, "skill", skill_id)
            session = client.post("/api/sessions").json()["session_id"]
            request = {"session_id": session, "skill_id": skill_id, "message": "分析过去7天"}
            denied = client.post("/api/chat/stream", json=request)
            self.assertEqual(denied.status_code, 409, denied.text)
            self.assertEqual(denied.json()["error_code"], "SKILL_DEPENDENCY_UNAVAILABLE")
            register(client, "tool", name)
            request["message"] = "排查光刻 Cpk 异常"
            asked = result(client.post("/api/chat/stream", json=request))
            self.assertEqual(asked["skill_execution"]["selection"], "manual")
            self.assertEqual(asked["skill_execution"]["status"], "clarification")
            self.assertIn("日期", asked["answer"])
            self.assertEqual(asked["tool_trace"], [])

            completed = result(client.post("/api/chat", json={
                "session_id": session, "message": "过去7天", "client_message_id": "skill-followup-001",
            }))
            self.assertEqual(completed["skill_execution"]["selection"], "followup")
            self.assertEqual(completed["skill_execution"]["status"], "executed")
            self.assertIn((name, "succeeded"), {
                (item["tool"], item["tool_status"]) for item in completed["tool_trace"]
            })
            cache = result(client.post("/api/chat/stream", json={
                "session_id": session, "message": "过去7天", "client_message_id": "skill-followup-001",
            }))
            self.assertTrue(cache["cached"])
            self.assertEqual(cache["run_id"], completed["run_id"])
            auto = result(client.post("/api/chat/stream", json={
                "session_id": session, "message": "排查过去7天光刻 Cpk 异常的原因",
            }))
            self.assertEqual(auto["skill_execution"]["selection"], "automatic")
            history = client.get(f"/api/sessions/{session}").json()["messages"]
            self.assertEqual(history[-1]["metadata"]["skill_execution"], auto["skill_execution"])

            from unittest.mock import AsyncMock

            synthesis = AsyncMock(return_value=(
                {"role": "assistant", "content": "请核对光刻制程能力数据和证据范围。"},
                {}, None, {},
            ))
            model_settings = replace(
                settings, model_connection=replace(
                    settings.model_connection, api_key="local-synthesis-fixture",
                    base_url="http://127.0.0.1:9",
                ),
            )
            with (
                patch("app.agent_runtime.service.effective_agent_settings", return_value=model_settings),
                patch("app.agent_runtime.service._request_ready_synthesis_session", synthesis),
                patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("network prohibited")),
            ):
                model_session = client.post("/api/sessions").json()["session_id"]
                modeled = result(client.post("/api/chat", json={
                    "session_id": model_session, "skill_id": skill_id,
                    "message": "排查过去7天光刻 Cpk 异常的原因",
                }))
                self.assertEqual(modeled["skill_execution"]["selection"], "manual")
                synthesis.assert_awaited_once()
                prompt_messages = synthesis.await_args.args[3]
                self.assertTrue(any("光刻" in message["content"] for message in prompt_messages if message["role"] == "system"))

            concept = result(client.post("/api/chat", json={
                "session_id": session, "message": "什么是 Cpk？",
            }))
            self.assertNotIn("skill_execution", concept)
            register(client, "skill", skill_id, access={"owner": "Litho"})
            denied = client.post("/api/chat", json=request)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json()["error_code"], "CAPABILITY_DENIED")
            denied = client.post("/api/chat", json={
                "session_id": session, "message": "过去7天", "client_message_id": "skill-followup-001",
            })
            self.assertEqual(denied.status_code, 403)

    @classmethod
    def setUpClass(cls):
        seed_reference_data()

    def test_tool_failure_code_survives_real_http_stream_and_session_reload(self):
        from uuid import uuid4

        from app.agent_runtime.execution.tool_result_bridge import project_tool_result
        from app.agent_runtime.tools.dispatch_contracts import PolicyDecision
        from tests import test_tool_dispatcher as tool_fixture

        calls = []
        async def agent(_question, _history, progress=None, **_kwargs):
            fixture = tool_fixture.DispatcherTests()
            def forbidden(*_args):
                calls.append("unexpected")
                raise AssertionError("denied handler must never run")
            dispatcher = fixture.dispatcher(fixture.binding(forbidden),
                policy=tool_fixture.Policy(PolicyDecision(False, "ROLE_DENIED", "password=secret")))
            result = await dispatcher.dispatch("native", {"value":"x"}, fixture.context())
            projection = project_tool_result(result)
            run_id = "error-catalog-" + uuid4().hex
            await progress({"event":"run_started", "run_id":run_id})
            await progress({"event":"tool_started", "tool":"native"})
            await progress(projection.event)
            return {"answer":"当前身份无权执行该查询。", "run_id":run_id,
                    "tool_trace":[projection.trace], "sources":[], "mode":"test", "model":"offline"}

        principal = tool_fixture.DispatcherTests().context().principal
        with patch("app.main.run_agent", new=agent), patch("app.main._validate_chat_model_capabilities", return_value=(principal,"offline")), TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            try:
                response = client.post("/api/chat/stream", json={"message":"查询设备状态", "session_id":session_id})
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.text.splitlines() if line]
                progress = next(item for item in events if item.get("event") == "tool_finished")
                self.assertEqual(progress["error_code"], "ROLE_DENIED")
                self.assertEqual(progress["recovery_action"], "request_access")
                self.assertFalse(progress["retryable"])
                self.assertIn("当前身份", progress["user_message"])
                self.assertNotIn("secret", response.text)
                self.assertEqual(events[-1]["type"], "result")
                saved = client.get(f"/api/sessions/{session_id}").json()["messages"][-1]["metadata"]
                self.assertEqual(saved["tool_trace"][0]["error_code"], "ROLE_DENIED")
                self.assertEqual(saved["tool_trace"][0]["user_message"], progress["user_message"])
                self.assertEqual(calls, [])
            finally:
                client.delete(f"/api/sessions/{session_id}/permanent")

    def test_sessions_are_isolated_by_tenant_and_user(self):
        owner_headers = {"X-Tenant-ID": "fab-a", "X-User-ID": "owner"}
        other_tenant_headers = {"X-Tenant-ID": "fab-b", "X-User-ID": "owner"}
        other_user_headers = {"X-Tenant-ID": "fab-a", "X-User-ID": "other"}
        with TestClient(app) as client:
            created = client.post("/api/sessions", headers=owner_headers)
            self.assertEqual(created.status_code, 200)
            session_id = created.json()["session_id"]

            self.assertEqual(client.get(f"/api/sessions/{session_id}", headers=owner_headers).status_code, 200)
            self.assertEqual(client.get(f"/api/sessions/{session_id}", headers=other_tenant_headers).status_code, 404)
            self.assertEqual(client.get(f"/api/sessions/{session_id}", headers=other_user_headers).status_code, 404)
            self.assertNotIn(session_id, {item["session_id"] for item in client.get("/api/sessions", headers=other_tenant_headers).json()})
            self.assertEqual(client.delete(f"/api/sessions/{session_id}/permanent", headers=owner_headers).status_code, 200)

    def test_session_messages_survive_reload(self):
        with TestClient(app) as client:
            created = client.post("/api/sessions")
            self.assertEqual(created.status_code, 200)
            session_id = created.json()["session_id"]
            append_message(session_id, "user", "分析 CMP-03")
            append_message(session_id, "assistant", "测试回答", {"tool_trace": [{"tool": "get_equipment_health", "status": "ok", "rows": 3}]})
            restored = client.get(f"/api/sessions/{session_id}")
            self.assertEqual(restored.status_code, 200)
            self.assertEqual([item["role"] for item in restored.json()["messages"]], ["user", "assistant"])
            self.assertEqual(restored.json()["messages"][1]["metadata"]["tool_trace"][0]["rows"], 3)
            client.delete(f"/api/sessions/{session_id}")

    def test_legacy_session_history_survives_restart_and_is_read_once_for_new_chat(self):
        legacy_user_metadata = {
            "legacy_version": "0.9",
            "source": {"channel": "old-client"},
        }
        legacy_assistant_metadata = {
            "legacy_version": "0.9",
            "tool_trace": [{"tool": "legacy_lookup", "rows": 2}],
        }
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            legacy_user = append_message(
                session_id,
                "user",
                "旧版提问",
                legacy_user_metadata,
            )
            legacy_assistant = append_message(
                session_id,
                "assistant",
                "旧版回答",
                legacy_assistant_metadata,
            )

        captured_histories: list[list[dict]] = []
        history_reads: list[tuple[str, int]] = []
        original_history = main.session_history

        def observe_history(read_session_id: str, limit: int = 20) -> list[dict]:
            history_reads.append((read_session_id, limit))
            return original_history(read_session_id, limit=limit)

        async def fake_agent(
            _question,
            history,
            _progress=None,
            *,
            thinking=False,
            thinking_effort="off",
            thinking_dialect="",
            session_id=None,
            user_message_id=None,
        ):
            captured_histories.append(history)
            return {
                "answer": "新回答",
                "run_id": "run-legacy-session-history",
                "model": "test-model",
                "mode": "test",
            }

        with (
            TestClient(app) as client,
            patch("app.main.session_history", new=observe_history),
            patch("app.main.run_agent", new=fake_agent),
        ):
            restored = client.get(f"/api/sessions/{session_id}").json()["messages"]
            self.assertEqual(
                [item["message_id"] for item in restored],
                [legacy_user["message_id"], legacy_assistant["message_id"]],
            )
            self.assertEqual(restored[0]["metadata"], legacy_user_metadata)
            self.assertEqual(restored[1]["metadata"], legacy_assistant_metadata)

            response = client.post(
                "/api/chat",
                json={
                    "message": "继续分析",
                    "session_id": session_id,
                    "history": [{"role": "user", "content": "显式历史不能被合并"}],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(history_reads, [(session_id, 20)])
            self.assertEqual(
                captured_histories,
                [[
                    {
                        "message_id": legacy_user["message_id"],
                        "role": "user",
                        "content": "旧版提问",
                        "metadata": legacy_user_metadata,
                    },
                    {
                        "message_id": legacy_assistant["message_id"],
                        "role": "assistant",
                        "content": "旧版回答",
                        "metadata": legacy_assistant_metadata,
                    },
                ]],
            )
            client.delete(f"/api/sessions/{session_id}/permanent")

    def test_session_history_can_list_rename_and_archive(self):
        with TestClient(app) as client:
            session = client.post("/api/sessions").json()
            append_message(session["session_id"], "user", "检查 ETCH-04 endpoint")
            listed = client.get("/api/sessions?q=ETCH-04").json()
            self.assertIn(session["session_id"], {item["session_id"] for item in listed})
            renamed = client.patch(f"/api/sessions/{session['session_id']}", json={"title": "ETCH endpoint 历史"})
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual(renamed.json()["title"], "ETCH endpoint 历史")
            archived = client.delete(f"/api/sessions/{session['session_id']}")
            self.assertEqual(archived.status_code, 200)
            active_ids = {item["session_id"] for item in client.get("/api/sessions").json()}
            self.assertNotIn(session["session_id"], active_ids)
            archived_sessions = client.get("/api/sessions?include_archived=true").json()
            archived_item = next(item for item in archived_sessions if item["session_id"] == session["session_id"])
            self.assertIsNotNone(archived_item["archived_at"])
            restored = client.post(f"/api/sessions/{session['session_id']}/restore")
            self.assertEqual(restored.status_code, 200)
            self.assertIsNone(restored.json()["archived_at"])
            active_ids = {item["session_id"] for item in client.get("/api/sessions").json()}
            self.assertIn(session["session_id"], active_ids)
            active_delete = client.delete(f"/api/sessions/{session['session_id']}/permanent")
            self.assertEqual(active_delete.status_code, 200)
            self.assertEqual(client.get(f"/api/sessions/{session['session_id']}").status_code, 404)

            archived_for_delete = client.post("/api/sessions").json()
            client.delete(f"/api/sessions/{archived_for_delete['session_id']}")
            deleted = client.delete(f"/api/sessions/{archived_for_delete['session_id']}/permanent")
            self.assertEqual(deleted.status_code, 200)
            self.assertTrue(deleted.json()["deleted"])
            self.assertEqual(client.get(f"/api/sessions/{archived_for_delete['session_id']}").status_code, 404)

    def test_sessions_can_be_deleted_in_bulk_with_agent_records(self):
        with TestClient(app) as client:
            active = client.post("/api/sessions").json()
            archived = client.post("/api/sessions").json()
            untouched = client.post("/api/sessions").json()
            assistant = append_message(active["session_id"], "assistant", "批量删除级联测试")
            record_agent_result(
                active["session_id"],
                assistant["message_id"],
                {
                    "run_id": "run-bulk-delete-test",
                    "model": "test-model",
                    "mode": "test",
                    "tool_trace": [{"tool": "get_fab_overview", "status": "ok", "rows": 1}],
                },
            )
            client.delete(f"/api/sessions/{archived['session_id']}")

            missing_id = "missing-session"
            response = client.post(
                "/api/sessions/bulk-delete",
                json={"session_ids": [active["session_id"], archived["session_id"], active["session_id"], missing_id]},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["deleted_count"], 2)
            self.assertEqual(payload["deleted_session_ids"], [active["session_id"], archived["session_id"]])
            self.assertEqual(payload["missing_session_ids"], [missing_id])
            self.assertEqual(client.get(f"/api/sessions/{active['session_id']}").status_code, 404)
            self.assertEqual(client.get(f"/api/sessions/{archived['session_id']}").status_code, 404)
            self.assertEqual(client.get(f"/api/sessions/{untouched['session_id']}").status_code, 200)
            with db_session() as connection:
                message_count = connection.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id IN (?, ?)",
                    (active["session_id"], archived["session_id"]),
                ).fetchone()[0]
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM agent_runs WHERE session_id IN (?, ?)",
                    (active["session_id"], archived["session_id"]),
                ).fetchone()[0]
                tool_count = connection.execute(
                    "SELECT COUNT(*) FROM agent_tool_events WHERE run_id = ?",
                    ("run-bulk-delete-test",),
                ).fetchone()[0]
            self.assertEqual((message_count, run_count, tool_count), (0, 0, 0))
            self.assertEqual(client.post("/api/sessions/bulk-delete", json={"session_ids": []}).status_code, 422)
            client.delete(f"/api/sessions/{untouched['session_id']}/permanent")

    def test_streaming_chat_emits_progress_before_result_and_persists(self):
        observed_thinking = []
        observed_correlation = []
        emitted = []
        plan = {
            "plan_id": "plan-stream-test",
            "schema_version": "1.0",
            "planner_version": "1.0.0",
            "status": "ready",
            "reason": "测试计划",
            "route_intent": "capability_excursion",
            "playbook_id": "PB-CAPABILITY-001",
            "playbook_version": "1.0.0",
            "required_evidence_ids": ["CAP-01"],
            "budget": {"planned_tool_calls": 1, "max_tool_calls": 2},
            "missing_inputs": [],
            "clarification_questions": [],
            "steps": [{
                "step_id": "S01",
                "title": "制程能力",
                "tool": "get_process_capability",
                "parameters": {"process_step": "CMP"},
                "parameter_sources": {"process_step": "intent_route.process_steps[0]"},
                "evidence_ids": ["CAP-01"],
                "depends_on": [],
                "required": True,
                "success_criteria": ["返回设备能力指标"],
                "estimated_result_limit": 100,
            }],
        }

        async def fake_agent(question, history, progress=None, *, thinking=False, thinking_effort="off", thinking_dialect="", session_id=None, user_message_id=None):
            observed_thinking.append((thinking, thinking_effort, thinking_dialect))
            observed_correlation.append((session_id, user_message_id))
            await progress({"event": "run_started", "run_id": "run-test", "message": "分析任务已创建"})
            await progress({"event": "stage", "stage": "plan", "message": "执行计划已生成", "plan": plan})
            await progress({"event": "tool_started", "tool": "get_process_capability", "arguments": {"process_step": "CMP"}})
            await progress({"event": "tool_finished", "tool": "get_process_capability", "arguments": {"process_step": "CMP"}, "status": "ok", "rows": 3})
            await progress({"event": "stage", "stage": "synthesis", "message": "正在汇总结论"})
            await progress({"event": "answer_delta", "delta": "CMP "})
            await progress({"event": "answer_delta", "delta": "分析完成"})
            return {
                "answer": "CMP 分析完成",
                "tool_trace": [{"tool": "get_process_capability", "arguments": {"process_step": "CMP"}, "status": "ok", "rows": 3}],
                "sources": [],
                "mode": "test",
                "run_id": "run-test",
            }

        def capture(event_type, run_id, **fields):
            emitted.append((event_type, run_id, fields))

        with patch("app.main.run_agent", new=fake_agent), patch("app.main.emit", new=capture), TestClient(app) as client:
            created = client.post("/api/sessions").json()
            response = client.post("/api/chat/stream", json={"message": "分析 CMP", "session_id": created["session_id"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(observed_thinking, [(False, "off", "deepseek")])
            self.assertEqual(observed_correlation[0][0], created["session_id"])
            events = [json.loads(line) for line in response.text.splitlines() if line]
            event_types = [event["type"] for event in events]
            self.assertEqual(event_types[0], "session")
            self.assertGreaterEqual(event_types.count("progress"), 5)
            self.assertEqual(event_types[-1], "result")
            self.assertLess(event_types.index("progress"), event_types.index("result"))
            answer_events = [event for event in events if event.get("event") == "answer_delta"]
            self.assertEqual("".join(event["delta"] for event in answer_events), "CMP 分析完成")
            delivery = next(event for event in events if event.get("event") == "stream_delivery_summary")
            self.assertGreaterEqual(delivery["answer_stream_duration_ms"], 0)
            restored = client.get(f"/api/sessions/{created['session_id']}").json()
            self.assertEqual([item["role"] for item in restored["messages"]], ["user", "assistant"])
            self.assertEqual(restored["messages"][1]["metadata"]["run_id"], "run-test")
            self.assertGreaterEqual(restored["messages"][1]["metadata"]["trace_semantics"]["stream_duration_ms"], 0)
            execution = restored["messages"][1]["metadata"]["execution"]
            self.assertEqual(execution["execution_status"], "completed")
            self.assertEqual(execution["steps"][0]["status"], "succeeded")
            progress_tools = [item for item in events if item.get("event") in {"tool_started", "tool_finished"}]
            self.assertEqual({item.get("step_id") for item in progress_tools}, {"S01"})
            audit = client.get("/api/agent-runs/run-test/audit")
            self.assertEqual(audit.status_code, 200, audit.text)
            self.assertEqual(audit.json()["tool_events"][0]["plan_step_id"], "S01")
            self.assertTrue(audit.json()["tool_events"][0]["started_at"])
            timeline = audit.json()["timeline"]
            self.assertEqual([item["replay_sequence"] for item in timeline], list(range(1, len(timeline) + 1)))
            self.assertEqual(timeline[0]["event"], "run_started")
            self.assertEqual(timeline[-1]["event"], "run_finished")
            self.assertTrue({"plan_created", "step_started", "tool_finished", "step_finished"}.issubset(
                {item["event"] for item in timeline}
            ))
            persisted = next(fields for event, run_id, fields in emitted if event == "agent_run_persisted" and run_id == "run-test")
            self.assertEqual(persisted["session_id"], created["session_id"])
            self.assertEqual(persisted["user_message_id"], observed_correlation[0][1])
            self.assertEqual(persisted["assistant_message_id"], restored["messages"][1]["message_id"])
            denied = client.get(
                "/api/agent-runs/run-test/audit",
                headers={"X-Tenant-ID": "demo-fab", "X-User-ID": "other-user"},
            )
            self.assertEqual(denied.status_code, 404)
            client.delete(f"/api/sessions/{created['session_id']}")

    def test_sanitized_real_chains_stream_and_persist_without_external_calls(self):
        dataset = load_trace_replay_dataset()
        current_date = date.fromisoformat(dataset["current_date"])
        cases = {
            case["question"]: case
            for case in dataset["cases"]
            if case.get("system_replay")
        }

        async def replay_agent(question, history, progress=None, *, thinking=False, thinking_effort="off", thinking_dialect="", session_id=None, user_message_id=None):
            result = replay_case(cases[question], current_date=current_date)
            for event in result["replay"]["progress_events"]:
                await progress(event)
            return result

        with patch("app.main.run_agent", new=replay_agent), TestClient(app) as client:
            for question, case in cases.items():
                with self.subTest(case=case["id"]):
                    session_id = client.post("/api/sessions").json()["session_id"]
                    response = client.post(
                        "/api/chat/stream",
                        json={"message": question, "session_id": session_id},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    events = [json.loads(line) for line in response.text.splitlines() if line]
                    final = events[-1]["result"]
                    streamed = "".join(
                        event.get("delta", "")
                        for event in events
                        if event.get("event") == "answer_delta"
                    )
                    self.assertEqual(streamed, final["answer"])
                    self.assertEqual(final["intent_route"]["intent"], case["expected"]["route"])
                    self.assertEqual(final["turn_decision"]["actions"][0]["type"], case["expected"]["action"])
                    self.assertEqual(final["trace_semantics"]["network_calls"], 0)
                    self.assertEqual(final["trace_semantics"]["real_model_calls"], 0)
                    self.assertEqual(final["trace_semantics"]["model_business_tool_selection_calls"], 0)
                    self.assertGreaterEqual(final["trace_semantics"]["stream_duration_ms"], 0)

                    restored = client.get(f"/api/sessions/{session_id}").json()
                    metadata = restored["messages"][-1]["metadata"]
                    self.assertEqual(metadata["replay"]["case_id"], case["id"])
                    self.assertEqual(metadata["execution_plan"]["scope_contract"]["primary_scope_type"], case["expected"]["primary_scope_type"])
                    self.assertEqual(metadata["replay"]["tool_path"], case["expected"]["tool_path"])
                    self.assertEqual(metadata["answer_synthesis"]["status"], final["answer_synthesis"]["status"])
                    client.delete(f"/api/sessions/{session_id}/permanent")

    def test_interrupted_plan_is_recovered_with_resume_boundary(self):
        with TestClient(app) as client:
            session = client.post("/api/sessions").json()
            user_message = append_message(session["session_id"], "user", "分析 CMP 中断恢复")
            run_id = "run-interruption-recovery-test"
            start_run_record(run_id, session["session_id"], user_message["message_id"], "分析 CMP 中断恢复", "test-model")
            persist_execution_plan(run_id, {
                "plan_id": "plan-interruption-recovery-test",
                "schema_version": "1.0",
                "planner_version": "1.0.0",
                "status": "ready",
                "route_intent": "capability_excursion",
                "required_evidence_ids": ["CAP-01", "CAP-02"],
                "steps": [
                    {
                        "step_id": "S01", "title": "能力", "tool": "get_process_capability",
                        "parameters": {"process_step": "CMP"}, "evidence_ids": ["CAP-01"],
                        "required": True,
                    },
                    {
                        "step_id": "S02", "title": "异常", "tool": "get_recent_excursions",
                        "parameters": {"process_step": "CMP"}, "evidence_ids": ["CAP-02"],
                        "depends_on": ["S01"], "required": True,
                    },
                ],
            })
            start_tool_event(run_id, "get_process_capability", {"process_step": "CMP"})

            recovered = recover_interrupted_executions("测试进程重启")
            self.assertGreaterEqual(recovered, 1)
            audit = client.get(f"/api/agent-runs/{run_id}/audit")
            self.assertEqual(audit.status_code, 200, audit.text)
            payload = audit.json()
            self.assertEqual(payload["run"]["status"], "interrupted")
            self.assertEqual(payload["execution"]["execution_status"], "interrupted")
            self.assertEqual(payload["execution"]["steps"][0]["status"], "interrupted")
            self.assertEqual(payload["execution"]["steps"][1]["status"], "pending")
            self.assertTrue(payload["execution"]["recovery"]["resumable"])
            self.assertEqual(payload["execution"]["recovery"]["resume_from_step_ids"], ["S01", "S02"])
            self.assertEqual(payload["tool_events"][0]["status"], "interrupted")
            client.delete(f"/api/sessions/{session['session_id']}/permanent")

    def test_admin_overview_tracks_user_agent_runtime(self):
        async def fake_agent(question, history, progress=None, *, thinking=False, thinking_effort="off", thinking_dialect="", session_id=None, user_message_id=None):
            await progress({"event": "run_started", "run_id": "run-admin-runtime", "message": "分析任务已创建"})
            await progress({"event": "answer_delta", "delta": "完成"})
            return {
                "answer": "运行状态测试完成",
                "tool_trace": [],
                "sources": [],
                "mode": "test",
                "model": "runtime-test-model",
                "run_id": "run-admin-runtime",
            }

        admin_token = "runtime-admin-token"
        user_headers = {"X-Tenant-ID": "runtime-fab", "X-User-ID": "operator-01"}
        with (
            patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": admin_token}),
            patch("app.main.run_agent", new=fake_agent),
            TestClient(app) as client,
        ):
            response = client.post("/api/chat/stream", headers=user_headers, json={"message": "检查运行状态"})
            self.assertEqual(response.status_code, 200, response.text)
            events = [json.loads(line) for line in response.text.splitlines() if line]
            session_id = next(item["session_id"] for item in events if item["type"] == "session")
            renamed = client.patch(
                f"/api/sessions/{session_id}",
                headers=user_headers,
                json={"title": "用户自定义的设备调查会话"},
            )
            self.assertEqual(renamed.status_code, 200, renamed.text)
            overview = client.get(
                "/api/admin/overview?hours=24",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(overview.status_code, 200, overview.text)
            user = next(
                item for item in overview.json()["users"]
                if item["tenant_id"] == "runtime-fab" and item["user_id"] == "operator-01"
            )
            self.assertEqual(user["status"], "idle")
            self.assertEqual(user["active_runs"], 0)
            self.assertEqual(user["model"], "runtime-test-model")
            self.assertGreaterEqual(user["run_count"], 1)
            recent_run = next(
                item for item in overview.json()["recent_runs"]
                if item["run_id"] == "run-admin-runtime"
            )
            self.assertEqual(recent_run["question_preview"], "检查运行状态")
            self.assertEqual(recent_run["session_id"], session_id)
            self.assertEqual(recent_run["session_title"], "用户自定义的设备调查会话")
            self.assertIsInstance(recent_run["user_message_id"], int)
            with db_session() as connection:
                persisted = connection.execute(
                    """SELECT r.question_preview, m.content, m.role
                       FROM agent_runs r JOIN chat_messages m ON m.message_id = r.user_message_id
                       WHERE r.run_id = ?""",
                    ("run-admin-runtime",),
                ).fetchone()
            self.assertEqual(tuple(persisted), ("检查运行状态", "检查运行状态", "user"))
            client.delete(f"/api/sessions/{session_id}/permanent", headers=user_headers)

    def test_stream_retry_with_same_client_message_id_is_idempotent(self):
        calls = 0

        async def fake_agent(question, history, progress=None, *, thinking=False, thinking_effort="off", thinking_dialect="", session_id=None, user_message_id=None):
            nonlocal calls
            calls += 1
            await progress({"event": "run_started", "run_id": "run-idempotent", "message": "分析任务已创建"})
            await progress({"event": "answer_delta", "delta": "完成"})
            return {
                "answer": "完成",
                "tool_trace": [],
                "sources": [],
                "mode": "test",
                "model": "test-model",
                "run_id": "run-idempotent",
            }

        payload_id = "msg-idempotent-0001"
        with patch("app.main.run_agent", new=fake_agent), TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            payload = {"message": "分析 CMP", "session_id": session_id, "client_message_id": payload_id}
            first = client.post("/api/chat/stream", json=payload)
            second = client.post("/api/chat/stream", json=payload)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            second_events = [json.loads(line) for line in second.text.splitlines() if line]
            self.assertTrue(second_events[-1]["result"]["cached"])
            self.assertEqual(calls, 1)
            conflict = client.post("/api/chat/stream", json={**payload, "message": "分析 ETCH"})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error_code"], "IDEMPOTENCY_CONFLICT")
            restored = client.get(f"/api/sessions/{session_id}").json()
            self.assertEqual([item["role"] for item in restored["messages"]], ["user", "assistant"])
            client.delete(f"/api/sessions/{session_id}/permanent")

    def test_stream_error_is_structured_and_audited(self):
        request_id = "req-stream-error-001"
        upstream_request = httpx.Request("POST", "https://example.test/chat/completions")

        async def failing_agent(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "upstream unavailable",
                request=upstream_request,
                response=httpx.Response(503, request=upstream_request),
            )

        with patch("app.main.run_agent", new=failing_agent), TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            response = client.post(
                "/api/chat/stream",
                json={"message": "分析 CMP", "session_id": session_id, "client_message_id": "msg-stream-error-001"},
                headers={"X-Request-ID": request_id},
            )
            events = [json.loads(line) for line in response.text.splitlines() if line]
            self.assertEqual(response.status_code, 200)
            self.assertEqual(events[-1]["type"], "error")
            self.assertEqual(events[-1]["error"]["error_code"], "MODEL_UPSTREAM_ERROR")
            self.assertEqual(events[-1]["detail"], "模型 API 返回 503")
            self.assertEqual(events[-1]["error"]["request_id"], request_id)
            self.assertTrue(events[-1]["error"]["retryable"])
            self.assertTrue(any(
                event.get("event") == "api_stream_error" and event.get("request_id") == request_id
                for event in read_events(200)
            ))
            client.delete(f"/api/sessions/{session_id}/permanent")

    def _mod031_roundtrip(self, *, mode="ready", streaming=True, checker_failure=False):
        """Real HTTP, coordinator, native SQLite Tools and committed session data.

        Only the model transport/capability catalog are offline fixtures. The
        loop variant selects the existing loop seam; it does not bypass the
        Dispatcher, checker, answer renderer or persistence implementation.
        """
        import gc
        from contextlib import ExitStack

        from app.bootstrap import evidence_assembly
        from app.core.identity import current_principal
        from tests import test_default_native_runtime as native_tests
        from tests import test_model_gateway_port as gateway_tests

        fixture = native_tests.DefaultNativeRuntimeTests()
        fixture.setUp()
        try:
            settings = fixture._settings(api_key="offline-fixture")
            raw = "已经证明虚构根因 MOD031-UNSUPPORTED，立即放行量产。"
            final_calls = []

            async def final_reply(_payload, progress, _state):
                # This is the actual model transport callback supplied by the
                # runtime. No provisional model answer can reach the HTTP queue.
                self.assertIsNone(progress)
                final_calls.append(True)
                if mode == "loop":
                    submission = {
                        "conclusion": raw, "facts": [{"statement": raw, "evidence_refs": []}],
                        "inferences": [], "hypotheses": [],
                        "recommendations": [{"action": "补充查询", "rationale": raw, "requires_review": True}],
                        "limitations": [raw], "source_refs": [],
                    }
                    return ({"role": "assistant", "content": "", "tool_calls": [{
                        "id": "mod031-submit", "type": "function", "function": {
                            "name": "submit_analysis", "arguments": json.dumps(submission)
                        }
                    }]}, {"total_tokens": 1}, "mod031-final")
                return ({"role": "assistant", "content": raw}, {"total_tokens": 1}, "mod031-final")

            async def tool_reply(payload, progress, _state):
                self.assertIsNone(progress)
                declaration = next(
                    item["content"].split("execution_plan=", 1)[1]
                    for item in payload["messages"] if "execution_plan=" in item.get("content", "")
                )
                plan = json.loads(declaration)
                return ({"role": "assistant", "content": "", "tool_calls": [
                    {"id": f"mod031-{step['step_id']}", "type": "function", "function": {
                        "name": step["tool"], "arguments": json.dumps(step["parameters"])
                    }} for step in plan["steps"]
                ]}, {"total_tokens": 1}, "mod031-tools")

            script = ([tool_reply] if mode == "loop" else []) + ([] if checker_failure else [final_reply])
            gateway = gateway_tests.ScriptedGateway(script)
            original = evidence_assembly.evaluate_evidence

            def check(plan, policy, observations, **kwargs):
                if checker_failure and (observations or checker_failure == "initial"):
                    raise RuntimeError("private connection detail MOD031-SECRET")
                return original(plan, policy, observations, **kwargs)

            async def select_loop(_state, *, deps):
                return None

            headers = {"X-Tenant-ID": "demo", "X-User-ID": "analyst", "X-Roles": "analyst"}
            diagnostic_errors = []
            def capture_error(_name, _run_id, **fields):
                if fields.get("error") or fields.get("error_message"):
                    diagnostic_errors.append((fields.get("error"), fields.get("error_message"), fields.get("full_content", {}).get("traceback")))
            with ExitStack() as stack:
                stack.enter_context(patch("app.agent_runtime.service.get_settings", return_value=settings))
                stack.enter_context(patch("app.agent_runtime.service.HttpModelGateway", new=lambda **_kw: gateway))
                stack.enter_context(patch("app.main._validate_chat_model_capabilities", new=lambda _request: (current_principal(), settings.model_connection.model, "off", "")))
                stack.enter_context(patch("app.main.emit", new=capture_error))
                stack.enter_context(patch("app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port", new=fixture._knowledge_port))
                stack.enter_context(patch("app.bootstrap.evidence_assembly.evaluate_evidence", new=check))
                if mode == "loop":
                    stack.enter_context(patch("app.agent_runtime.coordinator.execute_ready_synthesis", new=select_loop))
                client = stack.enter_context(TestClient(app))
                session = client.post("/api/sessions", headers=headers).json()["session_id"]
                try:
                    payload = {"message": "查询 LOT-001 的批次信息", "session_id": session,
                               "client_message_id": f"mod031-{mode}-{checker_failure}-{streaming}"}
                    response = client.post("/api/chat/stream" if streaming else "/api/chat", json=payload, headers=headers)
                    self.assertEqual(response.status_code, 200, (response.text, diagnostic_errors))
                    if streaming:
                        events = [json.loads(line) for line in response.text.splitlines() if line]
                        self.assertTrue(any(item["type"] == "result" for item in events), (response.text, diagnostic_errors))
                        result = next(item["result"] for item in events if item["type"] == "result")
                        visible = "".join(item.get("delta", "") for item in events if item.get("event") == "answer_delta")
                        self.assertEqual(visible, result["answer"])
                        self.assertNotIn("MOD031-UNSUPPORTED", visible)
                    else:
                        result = response.json()
                    self.assertNotIn("MOD031-UNSUPPORTED", result["answer"])
                    self.assertNotIn("MOD031-SECRET", json.dumps(result, ensure_ascii=False))
                    restored = client.get(f"/api/sessions/{session}", headers=headers).json()
                    assistant = restored["messages"][-1]
                    self.assertEqual(assistant["role"], "assistant")
                    self.assertEqual(assistant["content"], result["answer"])
                    self.assertEqual(assistant["metadata"]["evidence_validation"], result["evidence_validation"])
                    self.assertNotIn("MOD031-UNSUPPORTED", assistant["content"])
                    if checker_failure == "initial":
                        self.assertEqual(result["tool_trace"], [])
                    else:
                        self.assertTrue(result["tool_trace"])
                    self.assertTrue(all(item["status"] == "ok" for item in result["tool_trace"]))
                    self.assertEqual(result["evidence_validation"]["assessment_status"], "check_failed" if checker_failure else "checked")
                    self.assertEqual(len(gateway.requests), 0 if checker_failure == "initial" else (1 if mode == "loop" else 0) + (0 if checker_failure else 1))
                    self.assertEqual(len(final_calls), 0 if checker_failure else 1)
                    self.assertEqual(gateway.closed, len(gateway.opened))
                    requests = len(gateway.requests)
                    with patch("app.main.run_agent", side_effect=AssertionError("cached response must not execute again")):
                        replay = client.post("/api/chat/stream" if streaming else "/api/chat", json=payload, headers=headers)
                    self.assertEqual(replay.status_code, 200, replay.text)
                    replay_result = next(item["result"] for item in (json.loads(line) for line in replay.text.splitlines()) if item["type"] == "result") if streaming else replay.json()
                    self.assertEqual(replay_result["run_id"], result["run_id"])
                    self.assertEqual(replay_result["answer"], result["answer"])
                    self.assertEqual(len(gateway.requests), requests)
                    return result
                finally:
                    client.delete(f"/api/sessions/{session}/permanent", headers=headers)
        finally:
            gc.collect()
            fixture.tearDown()

    def test_mod031_ready_and_loop_stream_only_the_supported_final_answer(self):
        for mode in ("ready", "loop"):
            with self.subTest(mode=mode):
                self._mod031_roundtrip(mode=mode)

    def test_mod031_checker_failure_stops_model_synthesis_and_is_persisted(self):
        for mode in ("ready", "loop"):
            with self.subTest(mode=mode):
                result = self._mod031_roundtrip(mode=mode, checker_failure=True)
                self.assertEqual(result["evidence_validation"]["assessment_reason"], "checker_unavailable")
                self.assertIsNone(result["evidence_validation"]["evidence_sufficient"])

    def test_mod031_nonstream_http_uses_the_same_answer_constraints(self):
        self._mod031_roundtrip(streaming=False)

    def test_mod031_initial_check_failure_prevents_tool_and_model_execution(self):
        self._mod031_roundtrip(checker_failure="initial")


class DutyChatRegressionTests(unittest.TestCase):
    _tool = "get_equipment_event_timeline"
    _question = "查询 2026-08-07 CMP-02 报警次数"
    _lot = "LOT-DUTY-001"

    def setUp(self):
        from contextlib import closing
        from dataclasses import replace
        from pathlib import Path
        import sqlite3
        from tempfile import TemporaryDirectory

        from app.bootstrap import capability_catalog
        from app.core.settings import get_settings
        from app.demo_data.schemas import EQUIPMENT_SCHEMA, MANUFACTURING_SCHEMA

        root = Path(self.enterContext(TemporaryDirectory()))
        self.settings = get_settings()
        self.equipment_path = root / "equipment.db"
        self.manufacturing_path = root / "manufacturing.db"
        with closing(sqlite3.connect(self.equipment_path)) as db, db:
            db.executescript(EQUIPMENT_SCHEMA)
            db.executemany(
                """INSERT INTO equipment_events
                   (equipment_id, event_time, event_type, duration_minutes, severity, reason)
                   VALUES (?, ?, ?, 1, 'warning', 'synthetic duty fixture')""",
                [
                    ("CMP-02", "2026-08-07 00:00:00", "ALARM"),
                    ("CMP-02", "2026-08-07 23:59:00", "ALARM"),
                    ("CMP-02", "2026-08-07 12:00:00", "PM"),
                    ("CMP-03", "2026-08-07 12:00:00", "ALARM"),
                    ("CMP-02", "2026-08-08 00:00:00", "ALARM"),
                ],
            )
        with closing(sqlite3.connect(self.manufacturing_path)) as db, db:
            db.executescript(MANUFACTURING_SCHEMA)
            db.executemany(
                """INSERT INTO lots (
                       lot_id, product, technology_nm, route, priority, start_time,
                       status, wafer_count, good_wafers, yield_rate, cycle_time_hours, hold_hours
                   ) VALUES (?, ?, 28, 'fixture-route', 'normal', '2026-08-07', 'hold', 25, 24, 0.96, 12, 2)""",
                [(self._lot, "Duty-A"), ("LOT-DUTY-002", "Duty-B")],
            )
            db.executemany(
                """INSERT INTO process_runs (
                       lot_id, operation_seq, process_step, equipment_id, chamber, recipe,
                       run_time, temperature_c, pressure_torr, duration_sec, defect_density,
                       pass_flag, excursion_code
                   ) VALUES (?, ?, ?, ?, ?, 'fixture-recipe', ?, 25, 1, 10, 0.2, ?, ?)""",
                [
                    (self._lot, 20, "CMP", "CMP-02", "B", "2026-08-07 10:00:00", 0, "DUTY-CMP"),
                    (self._lot, 10, "ETCH", "ETCH-01", "A", "2026-08-07 09:00:00", 1, None),
                    ("LOT-DUTY-002", 10, "CMP", "CMP-02", "C", "2026-08-07 09:00:00", 1, None),
                ],
            )
        offline = replace(
            self.settings,
            model_connection=replace(self.settings.model_connection, api_key=""),
            equipment_database_path=self.equipment_path,
            manufacturing_database_path=self.manufacturing_path,
        )
        self.effective_settings = self.enterContext(patch(
            "app.agent_runtime.service.effective_agent_settings", return_value=offline,
        ))
        self.network = self.enterContext(patch.object(
            httpx.AsyncClient, "send", side_effect=AssertionError("external network prohibited"),
        ))
        self.enterContext(patch.object(capability_catalog, "db_path", return_value=root / "catalog.db"))
        self.client = self.enterContext(TestClient(app))
        self.session_ids = []
        self.addCleanup(self._cleanup_sessions)

    def _cleanup_sessions(self):
        for session_id in self.session_ids:
            self.client.delete(f"/api/sessions/{session_id}/permanent")
        self.network.assert_not_called()

    def _chat(self, message, *, session_id=None, stream=True):
        if session_id is None:
            created = self.client.post("/api/sessions")
            self.assertEqual(created.status_code, 200, created.text)
            session_id = created.json()["session_id"]
            self.session_ids.append(session_id)
        response = self.client.post(
            "/api/chat/stream" if stream else "/api/chat",
            json={"session_id": session_id, "message": message},
        )
        self.assertEqual(response.status_code, 200, response.text)
        if not stream:
            return response.json(), []
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(events[-1]["type"], "result", events)
        self.assertFalse([event for event in events if event["type"] == "error"], events)
        result = events[-1]["result"]
        self.assertEqual(
            "".join(event["delta"] for event in events if event.get("event") == "answer_delta"),
            result["answer"],
        )
        return result, events

    def _saved_answer(self, result):
        response = self.client.get(f"/api/sessions/{result['session_id']}")
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()["messages"][-1]
        self.assertEqual(saved["content"], result["answer"])
        return saved["metadata"]

    def _assert_alarm_plan(self, result, day):
        route = result["intent_route"]
        self.assertEqual((route["intent"], route["request_type"]), ("equipment_fault", "data_query"))
        plan = result["execution_plan"]
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(
            [(step["tool"], step["parameters"]) for step in plan["steps"]],
            [(self._tool, {"start": day, "end": day, "equipment_id": "CMP-02"})],
        )
        call, = result["tool_trace"]
        self.assertEqual(call["tool"], self._tool)
        return call

    def _assert_alarm_result(self, result, *, day, rows, alarms):
        call = self._assert_alarm_plan(result, day)
        self.assertEqual((call["tool_status"], call["rows"]), ("succeeded", rows))
        self.assertEqual(call["arguments"], {"start": day, "end": day, "equipment_id": "CMP-02"})
        source, = call["sources"]
        self.assertEqual(source["source_ref"], "sqlite:named-query/equipment_events")
        self.assertEqual(source["scope"]["equipment_ids"], ["CMP-02"])
        self.assertEqual((source["scope"]["start"], source["scope"]["end"]), (day, day))
        self.assertEqual(result["answer_synthesis"]["source_refs"], ["TOOL:S01"])
        for fragment in ("CMP-02", day, "日期口径", "设备事件时间线", f"记录了 {alarms} 条报警"):
            self.assertIn(fragment, result["answer"])
        saved = self._saved_answer(result)
        self.assertEqual(saved["execution_plan"], result["execution_plan"])
        self.assertEqual(saved["tool_trace"], result["tool_trace"])

    def _assert_shift_clarification(self, result, events):
        self.assertEqual(result["execution_plan"]["status"], "clarification_required")
        self.assertIn("supported_time_range", result["execution_plan"]["missing_inputs"])
        self.assertEqual(result["execution_plan"]["steps"], [])
        self.assertEqual(result["tool_trace"], [])
        self.assertFalse([event for event in events if event.get("event") == "tool_started"])
        self.assertIn("只支持日期范围", result["answer"])
        self.assertIn("全天记录", result["answer"])
        self.assertNotIn("条报警", result["answer"])

    def test_duty_reg_01_equipment_alarm_count_and_scope(self):
        result, events = self._chat(self._question)
        self._assert_alarm_result(result, day="2026-08-07", rows=3, alarms=2)
        finished, = [event for event in events if event.get("event") == "tool_finished"]
        self.assertEqual((finished["tool"], finished["tool_status"]), (self._tool, "succeeded"))

    def test_duty_reg_02_lot_history_preserves_identity_scope_and_order(self):
        from dataclasses import replace
        from unittest.mock import AsyncMock

        offline = self.effective_settings.return_value
        self.effective_settings.return_value = replace(
            offline, model_connection=replace(offline.model_connection, api_key="synthesis-fixture",
                                               base_url="http://127.0.0.1:9"),
        )
        synthesize = AsyncMock(return_value=(
            {"role": "assistant", "content": "综合夹具，须核对其来源。"}, {}, None, {},
        ))
        with patch("app.agent_runtime.service._request_ready_synthesis_session", synthesize):
            result, _ = self._chat(f"追踪批次 {self._lot}")
        self.assertEqual((result["intent_route"]["intent"], result["intent_route"]["request_type"]),
                         ("lot_trace", "data_query"))
        plan = result["execution_plan"]
        self.assertEqual((plan["status"], plan["playbook_id"]), ("ready", "PB-LOT-001"))
        names = [
            "get_lot_identity", "get_lot_process_history", "get_lot_excursion_history",
            "get_lot_defect_history", "get_lot_wafer_map_patterns",
        ]
        self.assertEqual([(step["tool"], step["parameters"]) for step in plan["steps"]],
                         [(name, {"lot_id": self._lot}) for name in names] + [
                             ("search_knowledge", {
                                 "query": f"追踪批次 {self._lot}", "limit": 10,
                                 "source_types": ["personal", "knowledge", "case"],
                             }),
                         ])
        by_tool = {call["tool"]: call for call in result["tool_trace"]}
        self.assertEqual(set(by_tool), set(names) | {"search_knowledge"})
        for name, rows in zip(names, (1, 2, 1, 0, 0), strict=True):
            call = by_tool[name]
            self.assertEqual((call["tool_status"], call["rows"]), ("succeeded", rows))
            source, = call["sources"]
            scope = source["scope"]
            self.assertEqual(scope["lot_ids"], [self._lot])
            self.assertIsNone(scope["start"])
            self.assertIsNone(scope["end"])
        synthesize.assert_awaited_once()
        task = json.loads(synthesize.await_args.args[3][-1]["content"])
        evidence = {entry["tool"]: entry for entry in task["evidence"]}
        lot, = evidence["get_lot_identity"]["result"]
        self.assertEqual((lot["lot_id"], lot["product"], lot["status"], lot["wafer_count"]),
                         (self._lot, "Duty-A", "hold", 25))
        records = evidence["get_lot_process_history"]["result"]
        self.assertEqual(
            [(row["lot_id"], row["operation_seq"], row["equipment_id"], row["chamber"]) for row in records],
            [(self._lot, 10, "ETCH-01", "A"), (self._lot, 20, "CMP-02", "B")],
        )
        excursion, = evidence["get_lot_excursion_history"]["result"]
        self.assertEqual((excursion["lot_id"], excursion["operation_seq"], excursion["excursion_code"]),
                         (self._lot, 20, "DUTY-CMP"))
        self.assertEqual(evidence["get_lot_process_history"]["source_ref"], "TOOL:S02")
        self.assertFalse(result["evidence_validation"]["evidence_sufficient"])
        self.assertIn("证据限制", result["answer"])
        self.assertEqual(self._saved_answer(result)["tool_trace"], result["tool_trace"])

    def test_duty_reg_03_handover_confirmation_inherits_equipment_and_metric(self):
        first, events = self._chat("交班时查询 2026-08-07 CMP-02 夜班报警次数")
        self._assert_shift_clarification(first, events)
        confirmed, _ = self._chat("改查 2026-08-07 全天", session_id=first["session_id"], stream=False)
        self._assert_alarm_result(confirmed, day="2026-08-07", rows=3, alarms=2)
        history = self.client.get(f"/api/sessions/{first['session_id']}").json()["messages"]
        self.assertEqual(history[-2]["content"], "改查 2026-08-07 全天")
        stale, _ = self._chat("改查 2026-08-08 全天", session_id=first["session_id"])
        self.assertEqual(stale["tool_trace"], [])

    def test_duty_reg_03_cpk_confirmation_preserves_the_metric(self):
        first, events = self._chat("查询 2026-08-07 夜班 CMP-02 Cpk 是多少")
        self._assert_shift_clarification(first, events)
        confirmed, _ = self._chat("确认 2026-08-07 全天数据", session_id=first["session_id"])
        plan = confirmed["execution_plan"]
        self.assertEqual((plan["status"], plan["playbook_id"]), ("ready", "PB-DUTY-CPK"))
        step, = plan["steps"]
        self.assertEqual(step["tool"], "get_process_capability")
        self.assertEqual(step["parameters"]["start"], "2026-08-07")
        self.assertEqual(step["parameters"]["end"], "2026-08-07")
        self.assertEqual(plan["scope_contract"]["primary_scope_ids"], ["CMP-02"])

    def test_duty_reg_03_unbound_or_invalid_confirmation_never_runs_tools(self):
        standalone, _ = self._chat("改查 2026-08-07 全天")
        self.assertEqual(standalone["tool_trace"], [])
        first, _ = self._chat("交班时查询 2026-08-07 CMP-02 夜班报警次数")
        invalid, _ = self._chat("改查 2026-02-30 全天", session_id=first["session_id"])
        self.assertEqual(invalid["tool_trace"], [])
        self.assertEqual(invalid["execution_plan"]["status"], "clarification_required")

    def test_duty_reg_04_cross_shift_is_not_widened_to_days(self):
        from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter

        with patch.object(SQLiteNamedQueryAdapter, "fetch") as fetch:
            result, events = self._chat("查询 2026-08-07 夜班到 2026-08-08 白班 CMP-02 报警次数")
        self._assert_shift_clarification(result, events)
        fetch.assert_not_called()

    def test_duty_reg_05_successful_empty_source_reports_zero(self):
        result, _ = self._chat("查询 2026-08-09 CMP-02 报警次数")
        self._assert_alarm_result(result, day="2026-08-09", rows=0, alarms=0)

    def test_duty_reg_06_source_failure_has_no_zero_count_or_evidence(self):
        from app.tools.named_queries.contracts import NamedQueryDataError
        from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter

        with patch.object(SQLiteNamedQueryAdapter, "fetch", side_effect=NamedQueryDataError("fixture failure")) as fetch:
            result, events = self._chat(self._question)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0].equipment_id, "CMP-02")
        self._assert_failed_alarm(result, events, "failed", "DATA_SOURCE_FAILED", "读取失败")

    def test_duty_reg_06_departments_enforce_tool_deny_before_source(self):
        from app.bootstrap import capability_catalog
        from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter

        first, _ = self._chat("交班时查询 2026-08-07 CMP-02 夜班报警次数")
        capability_catalog.save("tool", self._tool, {
            "enabled": True, "access": {"owner": "equipment-private", "readers": []}, "groups": [],
        })
        with patch.object(SQLiteNamedQueryAdapter, "fetch") as fetch:
            result, events = self._chat("改查 2026-08-07 全天", session_id=first["session_id"])
        fetch.assert_not_called()
        self._assert_failed_alarm(result, events, "denied", "TOOL_DENIED", "调用受限")

    def _assert_failed_alarm(self, result, events, status, code, text):
        call = self._assert_alarm_plan(result, "2026-08-07")
        self.assertEqual((call["tool_status"], call["error_code"]), (status, code))
        self.assertEqual(call["sources"], [])
        self.assertEqual(result["answer_synthesis"]["source_refs"], [])
        self.assertIn(text, result["answer"])
        self.assertNotIn("0 条报警", result["answer"])
        finished, = [event for event in events if event.get("event") == "tool_finished"]
        self.assertEqual(finished["error_code"], code)
        self.assertEqual(self._saved_answer(result)["tool_trace"], result["tool_trace"])


if __name__ == "__main__":
    unittest.main()
