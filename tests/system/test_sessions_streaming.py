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

from app.audit import read_events
from app.persistence.database import db_session
from app.persistence.execution_store import persist_execution_plan, recover_interrupted_executions, start_run_record, start_tool_event
from app.main import app
from app.manufacturing.seed import seed_reference_data
from app.sessions import append_message, record_agent_result
from scripts.evaluate_trace_replay import load_dataset as load_trace_replay_dataset, replay_case

class SessionsStreamingSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_reference_data()

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

        async def fake_agent(question, history, progress=None, *, thinking=False, session_id=None, user_message_id=None):
            observed_thinking.append(thinking)
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
            self.assertEqual(observed_thinking, [False])
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

        async def replay_agent(question, history, progress=None, *, thinking=False, session_id=None, user_message_id=None):
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
        async def fake_agent(question, history, progress=None, *, thinking=False, session_id=None, user_message_id=None):
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

        async def fake_agent(question, history, progress=None, *, thinking=False, session_id=None, user_message_id=None):
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

if __name__ == "__main__":
    unittest.main()
