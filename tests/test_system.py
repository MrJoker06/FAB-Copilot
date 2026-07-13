from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.audit import sanitize
from app.database import db_session
from app.main import app
from app.processes import MANUFACTURING_STEPS
from app.rag import search_knowledge
from app.reports import process_capability, recent_excursions, report_bundle, safe_select, timestamp_bounds
from app.seed import seed_reference_data
from app.sessions import append_message


class FabInsightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_reference_data()

    def test_dashboard_has_manufacturing_data(self):
        dashboard = report_bundle()
        self.assertGreater(dashboard["overview"]["lots"], 300)
        self.assertGreater(dashboard["overview"]["yield_pct"], 80)
        self.assertTrue(dashboard["equipment"])
        defect_types = [row["defect_type"] for row in dashboard["defects"]]
        self.assertEqual(len(defect_types), len(set(defect_types)))
        self.assertTrue(all("process_steps" in row for row in dashboard["defects"]))

    def test_seeded_cvd_drift_is_detectable(self):
        capability = process_capability(process_step="CVD")
        cvd_02 = next(row for row in capability if row["equipment_id"] == "CVD-02")
        peers = [row for row in capability if row["equipment_id"] != "CVD-02"]
        self.assertLess(cvd_02["cpk"], min(row["cpk"] for row in peers))

    def test_capability_range_is_sargable_and_keeps_end_date_inclusive(self):
        self.assertEqual(timestamp_bounds("2026-07-01", "2026-07-13"), ("2026-07-01", "2026-07-14"))
        with db_session() as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT equipment_id FROM process_runs "
                "WHERE process_step = ? AND run_time >= ? AND run_time < ?",
                ("CMP", "2026-07-01", "2026-07-14"),
            ).fetchall()
        self.assertTrue(any("idx_runs_step_time" in row[3] for row in plan), plan)

    def test_all_manufacturing_steps_have_equipment_and_capability(self):
        with db_session() as connection:
            rows = connection.execute(
                "SELECT process_step, COUNT(DISTINCT equipment_id) AS equipment_count "
                "FROM process_runs GROUP BY process_step"
            ).fetchall()
        equipment_counts = {row["process_step"]: row["equipment_count"] for row in rows}
        self.assertEqual(set(equipment_counts), set(MANUFACTURING_STEPS))
        self.assertTrue(all(count >= 3 for count in equipment_counts.values()))
        for step in MANUFACTURING_STEPS:
            with self.subTest(step=step):
                capability = process_capability(process_step=step)
                self.assertEqual(len(capability), equipment_counts[step])
                self.assertTrue(all(row["metric_name"] and row["metric_unit"] for row in capability))

    def test_expanded_fab_history_has_route_sensor_and_hidden_ground_truth(self):
        with db_session() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("lots", "process_runs", "sensor_readings", "equipment_state_intervals", "wafer_maps")
            }
            scenarios = connection.execute(
                "SELECT COUNT(*), SUM(visible_to_agent) FROM simulation_scenarios"
            ).fetchone()
            max_operation = connection.execute("SELECT MAX(operation_seq) FROM process_runs").fetchone()[0]
            signal_coverage = connection.execute(
                "SELECT process_step, COUNT(DISTINCT signal_name) FROM sensor_readings GROUP BY process_step"
            ).fetchall()
        self.assertGreaterEqual(counts["lots"], 9000)
        self.assertGreaterEqual(counts["process_runs"], 150000)
        self.assertGreaterEqual(counts["sensor_readings"], 1000000)
        self.assertGreater(counts["equipment_state_intervals"], 25000)
        self.assertEqual(counts["wafer_maps"], counts["lots"])
        self.assertEqual(tuple(scenarios), (9, 0))
        self.assertEqual(max_operation, 18)
        self.assertEqual({row[0] for row in signal_coverage}, set(MANUFACTURING_STEPS))
        self.assertTrue(all(row[1] >= 6 for row in signal_coverage))

    def test_history_contains_no_future_process_records(self):
        with db_session() as connection:
            max_run = connection.execute("SELECT MAX(date(run_time)) FROM process_runs").fetchone()[0]
            max_defect = connection.execute("SELECT MAX(date(detected_time)) FROM defect_records").fetchone()[0]
        self.assertLessEqual(max_run, date.today().isoformat())
        self.assertLessEqual(max_defect, date.today().isoformat())

    def test_recent_excursions_supports_process_filter(self):
        rows = recent_excursions(process_step="CMP", limit=20)
        self.assertTrue(rows)
        self.assertTrue(all(row["process_step"] == "CMP" for row in rows))

    def test_rag_returns_cited_source(self):
        results = search_knowledge("CMP 划伤 Pad Conditioner", 10)
        self.assertTrue(results)
        self.assertEqual({item["source_type"] for item in results}, {"knowledge", "case"})
        self.assertTrue(all(item["reference_id"] for item in results))
        self.assertTrue(all(item["retrieval"]["selection_reason"] for item in results))

    def test_rag_infers_chinese_process_and_defect_aliases(self):
        results = search_knowledge("刻蚀设备 CD 偏移的潜在原因", 6)
        self.assertTrue(results)
        self.assertEqual({item["source_type"] for item in results}, {"knowledge", "case"})
        self.assertTrue(all(item["retrieval"]["filters"]["process_step"] == "ETCH" for item in results))
        self.assertTrue(all(item["retrieval"]["filters"]["defect_type"] == "CD Shift" for item in results))

    def test_rag_gold_dataset(self):
        dataset_path = Path(__file__).resolve().parent.parent / "evaluations" / "rag_gold.json"
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        for item in dataset:
            with self.subTest(item=item["id"]):
                results = search_knowledge(item["query"], limit=6, **item.get("filters", {}))
                references = {result["reference_id"] for result in results}
                source_types = {result["source_type"] for result in results}
                self.assertTrue(references.intersection(item["expected_any"]))
                self.assertTrue(set(item.get("required_source_types", [])).issubset(source_types))
                self.assertFalse(references.intersection(item.get("forbidden", [])))

    def test_knowledge_documents_support_chunk_navigation(self):
        with TestClient(app) as client:
            documents = client.get("/api/knowledge/documents")
            self.assertEqual(documents.status_code, 200)
            self.assertGreaterEqual(len(documents.json()), 12)
            first_chunk_id = documents.json()[0]["first_chunk_id"]
            document = client.get(f"/api/knowledge/chunks/{first_chunk_id}")
            self.assertEqual(document.status_code, 200)
            self.assertEqual(document.json()["selected_chunk_id"], first_chunk_id)
            self.assertTrue(document.json()["chunks"])
            self.assertTrue(all("content" in chunk for chunk in document.json()["chunks"]))
            self.assertEqual(document.json()["document"]["status"], "Active")
            self.assertTrue(document.json()["document"]["version"])
            self.assertGreaterEqual(document.json()["document"]["authority"], 1)

    def test_historical_case_has_fixed_format(self):
        with TestClient(app) as client:
            cases = client.get("/api/cases")
            self.assertEqual(cases.status_code, 200)
            self.assertGreaterEqual(len(cases.json()), 12)
            case_id = cases.json()[0]["case_id"]
            detail = client.get(f"/api/cases/{case_id}")
            self.assertEqual(detail.status_code, 200)
            required = {
                "problem", "solution", "result", "summary", "root_cause",
                "root_cause_confidence", "validation_method", "recurrence_status",
                "approved_by", "case_status",
            }
            self.assertTrue(required.issubset(detail.json()))
            self.assertTrue(all(detail.json()[field] for field in required))

    def test_sql_guard_rejects_writes(self):
        with self.assertRaises(ValueError):
            safe_select("DELETE FROM lots")
        with self.assertRaises(ValueError):
            safe_select("SELECT * FROM sqlite_master")
        with self.assertRaises(ValueError):
            safe_select("SELECT scenario_id FROM process_runs")

    def test_health_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(response.json()["reference_data"]["knowledge_chunks"], 68)
            self.assertEqual(response.json()["reference_data"]["historical_cases"], 17)

    def test_monitor_endpoint_is_sanitized(self):
        with TestClient(app) as client:
            response = client.get("/api/monitor/summary?hours=24")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("runs", payload)
            self.assertNotIn("api_key", str(payload).lower())

    def test_model_can_be_switched_without_exposing_key(self):
        with TestClient(app) as client:
            initial = client.get("/api/settings/model")
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["allowed_models"], ["deepseekv4-flash", "deepseekv4-pro"])
            response = client.post("/api/settings/model", json={
                "model": "deepseekv4-pro",
                "api_key": "test-secret-api-key",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["model"], "deepseekv4-pro")
            self.assertEqual(response.json()["provider_model"], "deepseek-v4-pro")
            self.assertNotIn("test-secret-api-key", response.text)
            client.post("/api/settings/model", json={"model": "deepseekv4-flash"})

    def test_unknown_model_is_rejected(self):
        with TestClient(app) as client:
            response = client.post("/api/settings/model", json={"model": "unknown-model"})
            self.assertEqual(response.status_code, 400)

    def test_full_logging_still_redacts_credentials(self):
        payload = sanitize({
            "DEEPSEEK_API_KEY": "secret-key",
            "headers": {"Authorization": "Bearer secret-token"},
            "input_tokens": 42,
        })
        self.assertEqual(payload["DEEPSEEK_API_KEY"], "<redacted>")
        self.assertEqual(payload["headers"]["Authorization"], "<redacted>")
        self.assertEqual(payload["input_tokens"], 42)

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

    def test_streaming_chat_emits_progress_before_result_and_persists(self):
        async def fake_agent(question, history, progress=None):
            await progress({"event": "run_started", "run_id": "run-test", "message": "分析任务已创建"})
            await progress({"event": "stage", "stage": "planning", "message": "正在规划分析路径"})
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

        with patch("app.main.run_agent", new=fake_agent), TestClient(app) as client:
            created = client.post("/api/sessions").json()
            response = client.post("/api/chat/stream", json={"message": "分析 CMP", "session_id": created["session_id"]})
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in response.text.splitlines() if line]
            event_types = [event["type"] for event in events]
            self.assertEqual(event_types[0], "session")
            self.assertGreaterEqual(event_types.count("progress"), 5)
            self.assertEqual(event_types[-1], "result")
            self.assertLess(event_types.index("progress"), event_types.index("result"))
            answer_events = [event for event in events if event.get("event") == "answer_delta"]
            self.assertEqual("".join(event["delta"] for event in answer_events), "CMP 分析完成")
            restored = client.get(f"/api/sessions/{created['session_id']}").json()
            self.assertEqual([item["role"] for item in restored["messages"]], ["user", "assistant"])
            self.assertEqual(restored["messages"][1]["metadata"]["run_id"], "run-test")
            client.delete(f"/api/sessions/{created['session_id']}")


if __name__ == "__main__":
    unittest.main()
