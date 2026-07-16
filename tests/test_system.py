from __future__ import annotations

import atexit
import asyncio
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx


TEST_DATABASE_DIR = Path(tempfile.mkdtemp(prefix="fab-insight-tests-"))
os.environ["FAB_KNOWLEDGE_DATABASE_PATH"] = str(TEST_DATABASE_DIR / "process_knowledge.db")
os.environ["FAB_AGENT_DATABASE_PATH"] = str(TEST_DATABASE_DIR / "ai_operations.db")
os.environ["FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH"] = str(TEST_DATABASE_DIR / "personal_knowledge")
atexit.register(shutil.rmtree, TEST_DATABASE_DIR, True)

from fastapi.testclient import TestClient

from app.audit import read_events, sanitize
from app import agent as agent_module
from app.database import (
    db_session,
    department_paths,
    get_active_defect_aliases,
    initialize,
    replace_defect_type_aliases,
    sqlite_journal_mode,
)
from app.main import app
from app.processes import MANUFACTURING_STEPS
from app.rag import (
    _case_sql_filters,
    _fts_query,
    _infer_filters,
    _knowledge_sql_filters,
    _metadata_rerank,
    _tokenize_query,
    search_knowledge,
)
from app.reports import process_capability, recent_excursions, report_bundle, safe_select, timestamp_bounds
from app.seed import seed_reference_data
from app.sessions import append_message, record_agent_result


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

    def test_frontend_exposes_personal_knowledge_upload_workflow(self):
        with TestClient(app) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        for element_id in (
            "knowledgeSourceTabs",
            "openKnowledgeUpload",
            "knowledgeUploadDialog",
            "knowledgeUploadFile",
            "personalKnowledgeActions",
            "personalKnowledgeDeleteDialog",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("/static/app.js?v=20260716-6", page)
        styles = (Path(__file__).parents[1] / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("scrollbar-gutter: stable", styles)
        script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-personal-chunk", script)

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
            max_wafer_map = connection.execute("SELECT MAX(date(detected_time)) FROM wafer_maps").fetchone()[0]
        self.assertLessEqual(max_run, date.today().isoformat())
        self.assertLessEqual(max_defect, date.today().isoformat())
        self.assertLessEqual(max_wafer_map, date.today().isoformat())

    def test_department_databases_are_physically_separated(self):
        paths = department_paths()
        self.assertEqual(set(paths), {"main", "equipment", "quality", "knowledge", "agent"})
        self.assertEqual(len(set(paths.values())), 5)
        self.assertTrue(all(path.exists() for path in paths.values()))
        with db_session() as connection:
            attached = {row[1] for row in connection.execute("PRAGMA database_list")}
        self.assertTrue({"main", "equipment", "quality", "knowledge", "agent"}.issubset(attached))

    def test_sqlite_journal_mode_is_safe_for_wsl_mounted_databases(self):
        with patch.dict(os.environ, {"FAB_SQLITE_JOURNAL_MODE": "auto"}):
            self.assertEqual(sqlite_journal_mode(Path("/mnt/d/fab.db")), "DELETE")
            self.assertEqual(sqlite_journal_mode(Path("/tmp/fab.db")), "WAL")
        with patch.dict(os.environ, {"FAB_SQLITE_JOURNAL_MODE": "TRUNCATE"}):
            self.assertEqual(sqlite_journal_mode(Path("/mnt/d/fab.db")), "TRUNCATE")

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
        self.assertTrue(all(item["retrieval"]["score_version"] == "rrf-metadata-v2" for item in results))
        knowledge_results = [item for item in results if item["source_type"] == "knowledge"]
        self.assertTrue(all(item["content"] for item in knowledge_results))
        self.assertTrue(any(len(item["content"]) > len(item["excerpt"]) for item in knowledge_results))

    def test_agent_removes_fabricated_citations_and_marks_retrieved_content_untrusted(self):
        sources = {"KB-2": {"reference_id": "KB-2"}}
        cleaned, validation = agent_module._sanitize_answer_citations(
            "结论 [来源 KB-2]，伪造内容 [来源 KB-999]。",
            sources,
        )
        self.assertIn("[来源 KB-2]", cleaned)
        self.assertNotIn("KB-999", cleaned)
        self.assertEqual(validation["invalid_citations_removed"], ["KB-999"])
        self.assertIn("不可信数据", agent_module.SYSTEM_PROMPT)

        uncited, validation = agent_module._sanitize_answer_citations("有检索证据但未引用。", sources)
        self.assertIn("候选来源", uncited)
        self.assertIn("[来源 KB-2]", uncited)
        self.assertTrue(validation["fallback_appended"])

        no_source, validation = agent_module._sanitize_answer_citations(
            "没有检索却声称存在依据 [来源 KB-404]。",
            {},
        )
        self.assertNotIn("KB-404", no_source)
        self.assertEqual(validation["invalid_citations_removed"], ["KB-404"])
        self.assertFalse(validation["fallback_appended"])

        malformed, validation = agent_module._sanitize_answer_citations(
            "畸形引用 [来源 ../../KB-2] 和 [来源 KB-2 extra]。",
            sources,
        )
        self.assertNotIn("[来源 ../../KB-2]", malformed)
        self.assertNotIn("[来源 KB-2 extra]", malformed)
        self.assertIn("[来源 KB-2]", malformed)
        self.assertEqual(
            validation["malformed_citations_removed"],
            ["[来源 ../../KB-2]", "[来源 KB-2 extra]"],
        )

    def test_rag_tokenization_deduplicates_and_builds_chinese_trigrams(self):
        tokens = _tokenize_query("光刻技术原理 光刻技术原理 CMP CMP")
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertLessEqual(len(tokens), 20)
        self.assertTrue({"光刻技", "刻技术", "技术原", "术原理", "CMP"}.issubset(tokens))

    def test_rag_filter_inference_respects_explicit_defect_and_equipment(self):
        filters = _infer_filters("CMP-03 划伤", None, None, "Overlay")
        self.assertEqual(filters["process_step"], "CMP")
        self.assertEqual(filters["equipment_id"], "CMP-03")
        self.assertEqual(filters["defect_type"], "Overlay")

        explicit = _infer_filters("文本中出现 CMP-03 Scratch", "ETCH", "etch-02", "Particle")
        self.assertEqual(
            explicit,
            {"process_step": "ETCH", "equipment_id": "ETCH-02", "defect_type": "Particle"},
        )

    def test_rag_sql_filters_are_parameterized_and_governed(self):
        filters = {"process_step": "CMP", "equipment_id": "CMP-03", "defect_type": "Scratch"}
        knowledge_clauses, knowledge_params = _knowledge_sql_filters(filters)
        case_clauses, case_params = _case_sql_filters(filters)
        self.assertTrue(knowledge_clauses)
        self.assertEqual(knowledge_params, ["CMP"])
        self.assertIn("case_status = 'Validated'", case_clauses[0])
        self.assertEqual(case_params, ["CMP", "CMP", "Scratch"])
        self.assertTrue(all("CMP" not in clause and "Scratch" not in clause for clause in case_clauses))

    def test_rag_deduplicates_references_and_suppresses_low_confidence_when_possible(self):
        candidates = [
            {
                "reference_id": "KB-1",
                "source_type": "knowledge",
                "process_steps": "ALL",
                "authority": 5,
                "title": "正式知识",
                "section": "概述",
                "tags": "",
            },
            {
                "reference_id": "KB-1",
                "source_type": "knowledge",
                "process_steps": "ALL",
                "authority": 5,
                "title": "重复知识",
                "section": "概述",
                "tags": "",
            },
            {
                "reference_id": "CASE-LOW-1",
                "source_type": "case",
                "case_status": "Validated",
                "process_step": "CMP",
                "equipment_family": "CMP",
                "root_cause_confidence": 0.1,
                "occurred_date": "2020-01-01",
            },
        ]
        results = _metadata_rerank(
            candidates,
            {"process_step": None, "equipment_id": None, "defect_type": None},
            5,
            None,
        )
        self.assertEqual([item["reference_id"] for item in results], ["KB-1"])

        low_only = _metadata_rerank(
            candidates[-1:],
            {"process_step": None, "equipment_id": None, "defect_type": None},
            5,
            ["case"],
        )
        self.assertEqual([item["reference_id"] for item in low_only], ["CASE-LOW-1"])
        self.assertEqual(low_only[0]["retrieval"]["confidence"], "low")

    def test_rag_returns_empty_for_query_without_searchable_terms_or_mismatched_defect(self):
        self.assertEqual(search_knowledge("!!", 6), [])
        mismatch = search_knowledge(
            "CMP-03 Pad Conditioner 划伤",
            6,
            process_step="CMP",
            equipment_id="CMP-03",
            defect_type="Overlay",
            source_types=["case"],
        )
        self.assertEqual(mismatch, [])

    def test_rag_source_quota_preserves_three_source_evidence(self):
        candidates = []
        for index in range(8):
            candidates.append({
                "reference_id": f"PERSONAL-{index}",
                "source_type": "personal",
                "process_steps": ["CMP"],
                "equipment_ids": [],
                "title": f"个人记录 {index}",
                "tags": [],
            })
        for index in range(5):
            candidates.append({
                "reference_id": f"KB-{100 + index}",
                "source_type": "knowledge",
                "process_steps": "CMP",
                "authority": 5,
                "title": f"正式知识 {index}",
                "section": "CMP",
                "tags": "CMP",
            })
        for index in range(2):
            candidates.append({
                "reference_id": f"CASE-QUOTA-{index}",
                "source_type": "case",
                "case_status": "Validated",
                "process_step": "CMP",
                "equipment_family": "CMP",
                "equipment_id": f"CMP-{index + 1:02d}",
                "root_cause_confidence": 0.9,
                "occurred_date": "2026-01-01",
                "defect_type": "Scratch",
            })
        results = _metadata_rerank(
            candidates,
            {"process_step": "CMP", "equipment_id": None, "defect_type": None},
            limit=6,
            source_types=None,
        )
        counts = {
            source_type: sum(item["source_type"] == source_type for item in results)
            for source_type in ("personal", "knowledge", "case")
        }
        self.assertEqual(len(results), 6)
        self.assertTrue(all(counts[source_type] >= 1 for source_type in counts))
        self.assertLessEqual(counts["personal"], 4)

    def test_rag_source_type_filter_never_mixes_namespaces(self):
        query = "CMP 划伤 Pad Conditioner"
        knowledge = search_knowledge(query, 6, source_types=["knowledge"])
        cases = search_knowledge(query, 6, source_types=["case"])
        self.assertTrue(knowledge)
        self.assertTrue(cases)
        self.assertEqual({item["source_type"] for item in knowledge}, {"knowledge"})
        self.assertEqual({item["source_type"] for item in cases}, {"case"})

    def test_rag_filters_draft_cases_before_candidate_limit(self):
        draft_prefix = "CASE-DRAFT-FILTER-"
        query = "CMP-03 跨产品持续划伤 Pad Conditioner 潜在原因"
        fts_query = _fts_query(f"{query} CMP CMP-03 Scratch")
        drafts = []
        exact_text = "CMP-03 Scratch Pad Conditioner 跨产品持续划伤 潜在原因"
        for index in range(60):
            drafts.append({
                "case_id": f"{draft_prefix}{index:03d}",
                "title": exact_text,
                "process_step": "CMP",
                "equipment_id": "CMP-03",
                "occurred_date": "2026-01-01",
                "severity": "High",
                "problem": exact_text,
                "solution": exact_text,
                "result": exact_text,
                "summary": exact_text,
                "tags": "CMP,Scratch,Pad,Conditioner",
                "equipment_family": "CMP",
                "defect_type": "Scratch",
                "symptoms": exact_text,
                "root_cause": "未验证草稿根因",
                "root_cause_confidence": 0.1,
                "validation_method": "None",
                "recurrence_status": "Unknown",
                "approved_by": "",
                "case_status": "Draft",
            })
        try:
            with db_session() as connection:
                connection.executemany(
                    """INSERT INTO knowledge.historical_cases(
                           case_id, title, process_step, equipment_id, occurred_date, severity,
                           problem, solution, result, summary, tags, equipment_family, defect_type,
                           symptoms, root_cause, root_cause_confidence, validation_method,
                           recurrence_status, approved_by, case_status
                       ) VALUES (
                           :case_id, :title, :process_step, :equipment_id, :occurred_date, :severity,
                           :problem, :solution, :result, :summary, :tags, :equipment_family, :defect_type,
                           :symptoms, :root_cause, :root_cause_confidence, :validation_method,
                           :recurrence_status, :approved_by, :case_status
                       )""",
                    drafts,
                )
                connection.execute(
                    "INSERT INTO knowledge.case_trigram_fts(case_trigram_fts) VALUES ('rebuild')"
                )
                raw_candidates = connection.execute(
                    """SELECT c.case_id FROM knowledge.case_trigram_fts
                       JOIN knowledge.historical_cases c ON c.rowid = case_trigram_fts.rowid
                       WHERE case_trigram_fts MATCH ?
                       ORDER BY bm25(case_trigram_fts) LIMIT 30""",
                    (fts_query,),
                ).fetchall()
                connection.commit()
            self.assertEqual(len(raw_candidates), 30)
            self.assertTrue(all(row["case_id"].startswith(draft_prefix) for row in raw_candidates))

            results = search_knowledge(
                query,
                limit=6,
                process_step="CMP",
                equipment_id="CMP-03",
                defect_type="Scratch",
                source_types=["case"],
            )
            references = {item["reference_id"] for item in results}
            self.assertIn("CASE-CMP-001", references)
            self.assertFalse(any(reference.startswith(draft_prefix) for reference in references))
        finally:
            with db_session() as connection:
                connection.execute(
                    "DELETE FROM knowledge.historical_cases WHERE case_id LIKE ?",
                    (f"{draft_prefix}%",),
                )
                connection.execute(
                    "INSERT INTO knowledge.case_trigram_fts(case_trigram_fts) VALUES ('rebuild')"
                )
                connection.commit()

    def test_rag_infers_chinese_process_and_defect_aliases(self):
        results = search_knowledge("刻蚀设备 CD 偏移的潜在原因", 6)
        self.assertTrue(results)
        self.assertEqual({item["source_type"] for item in results}, {"knowledge", "case"})
        self.assertTrue(all(item["retrieval"]["filters"]["process_step"] == "ETCH" for item in results))
        self.assertTrue(all(item["retrieval"]["filters"]["defect_type"] == "CD Shift" for item in results))

    def test_rag_uses_database_managed_defect_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "aliases.db"
            initialize(database_path)
            replace_defect_type_aliases("Pattern Collapse", ("pattern collapse", "图形倒塌"), database_path)
            aliases = get_active_defect_aliases(database_path)
        with patch("app.rag.get_active_defect_aliases", return_value=aliases):
            filters = _infer_filters("光刻后出现图形倒塌", None, None, None)
        self.assertEqual(filters["defect_type"], "Pattern Collapse")

    def test_rag_gold_dataset(self):
        dataset_path = Path(__file__).resolve().parent.parent / "evaluations" / "rag_gold.json"
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        for item in dataset:
            with self.subTest(item=item["id"]):
                results = search_knowledge(item["query"], limit=6, **item.get("filters", {}))
                references = {result["reference_id"] for result in results}
                source_types = {result["source_type"] for result in results}
                if item.get("expect_empty"):
                    self.assertFalse(references)
                else:
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

    def test_personal_knowledge_upload_search_privacy_and_delete(self):
        content = (
            "# CMP-03 Pad 更换记录\n\n"
            "2026-07-01 完成 Pad 更换。更换后确认主轴电流稳定，抛光压力恢复正常。\n\n"
            "## 验证结果\n\n"
            "连续三个批次膜厚均匀性满足要求，Scratch 缺陷未再次出现。"
        ).encode("utf-8")
        headers = {"Idempotency-Key": "personal-upload-test-001"}
        metadata = json.dumps({
            "title": "CMP-03 Pad 更换记录",
            "process_steps": ["CMP"],
            "equipment_ids": ["CMP-03"],
            "effective_date": "2026-07-01",
            "tags": ["pad", "maintenance"],
        }, ensure_ascii=False)

        with TestClient(app) as client:
            uploaded = client.post(
                "/api/knowledge/personal/documents",
                headers=headers,
                files={"file": ("cmp-pad.md", content, "text/markdown")},
                data={"metadata": metadata},
            )
            self.assertEqual(uploaded.status_code, 202, uploaded.text)
            document_id = uploaded.json()["document_id"]
            job_id = uploaded.json()["job_id"]

            job = client.get(f"/api/knowledge/jobs/{job_id}")
            self.assertEqual(job.status_code, 200)
            self.assertEqual(job.json()["status"], "ready")
            self.assertEqual(job.json()["progress"], 100)

            listed = client.get("/api/knowledge/personal/documents?status=ready&q=CMP")
            self.assertEqual(listed.status_code, 200)
            self.assertIn(document_id, {item["document_id"] for item in listed.json()["items"]})

            detail = client.get(f"/api/knowledge/personal/documents/{document_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["process_steps"], ["CMP"])
            self.assertGreater(detail.json()["chunk_count"], 0)
            self.assertNotIn("owner_user_id", detail.json())
            self.assertNotIn("storage_key", detail.json())

            document_content = client.get(f"/api/knowledge/personal/documents/{document_id}/content")
            self.assertEqual(document_content.status_code, 200)
            self.assertTrue(document_content.json()["chunks"])
            chunk_id = document_content.json()["chunks"][0]["chunk_id"]
            with db_session() as connection:
                indexed_chunks = connection.execute(
                    "SELECT COUNT(*) FROM personal_knowledge_fts WHERE document_id = ?", (document_id,)
                ).fetchone()[0]
            self.assertEqual(indexed_chunks, detail.json()["chunk_count"])

            search = client.post(
                "/api/knowledge/personal/search-preview",
                json={"query": "CMP-03 Pad 更换后 Scratch 验证", "document_ids": [document_id]},
            )
            self.assertEqual(search.status_code, 200, search.text)
            self.assertGreater(search.json()["count"], 0)
            self.assertTrue(all(item["source_type"] == "personal" for item in search.json()["results"]))
            self.assertTrue(all(item["content"] for item in search.json()["results"]))

            chunk = client.get(f"/api/knowledge/personal/chunks/{chunk_id}")
            self.assertEqual(chunk.status_code, 200)
            self.assertEqual(chunk.json()["document_id"], document_id)

            updated = client.patch(
                f"/api/knowledge/personal/documents/{document_id}",
                json={"title": "CMP-03 Pad 更换与验证记录", "tags": ["pad", "verified"]},
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["title"], "CMP-03 Pad 更换与验证记录")

            downloaded = client.get(f"/api/knowledge/personal/documents/{document_id}/file")
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.content, content)

            replay = client.post(
                "/api/knowledge/personal/documents",
                headers=headers,
                files={"file": ("cmp-pad.md", content, "text/markdown")},
                data={"metadata": metadata},
            )
            self.assertEqual(replay.status_code, 202)
            self.assertEqual(replay.json()["document_id"], document_id)
            self.assertEqual(replay.json()["job_id"], job_id)

            duplicate = client.post(
                "/api/knowledge/personal/documents",
                headers={"Idempotency-Key": "personal-upload-test-002"},
                files={"file": ("duplicate.md", content, "text/markdown")},
            )
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json()["error_code"], "DUPLICATE_DOCUMENT")

            with patch.dict(os.environ, {"FAB_PERSONAL_KNOWLEDGE_USER_ID": "different-user"}):
                self.assertEqual(client.get(f"/api/knowledge/personal/documents/{document_id}").status_code, 404)
                self.assertEqual(client.get(f"/api/knowledge/personal/chunks/{chunk_id}").status_code, 404)
                self.assertEqual(client.get(f"/api/knowledge/jobs/{job_id}").status_code, 404)
                private_search = client.post(
                    "/api/knowledge/personal/search-preview",
                    json={"query": "CMP Pad", "document_ids": [document_id]},
                )
                self.assertEqual(private_search.status_code, 404)

            deleting = client.delete(f"/api/knowledge/personal/documents/{document_id}")
            self.assertEqual(deleting.status_code, 202, deleting.text)
            delete_job_id = deleting.json()["job_id"]
            self.assertEqual(client.get(f"/api/knowledge/jobs/{delete_job_id}").json()["status"], "deleted")
            self.assertEqual(client.get(f"/api/knowledge/personal/documents/{document_id}").status_code, 404)
            self.assertEqual(client.get(f"/api/knowledge/personal/chunks/{chunk_id}").status_code, 404)
            with db_session() as connection:
                indexed_chunks = connection.execute(
                    "SELECT COUNT(*) FROM personal_knowledge_fts WHERE document_id = ?", (document_id,)
                ).fetchone()[0]
            self.assertEqual(indexed_chunks, 0)

    def test_agent_search_combines_private_knowledge_with_cross_language_recall(self):
        content = (
            "# Introduction to Photolithography\n\n"
            "Photolithography transfers a reticle pattern into photoresist by optical exposure.\n\n"
            "## Process basics\n\n"
            "The basic sequence covers coat, soft bake, align, expose, develop, inspect, and pattern transfer."
        ).encode("utf-8")
        metadata = json.dumps({
            "title": "Introduction to Photolithography",
            "process_steps": ["LITHO"],
            "tags": ["training", "fundamentals"],
        })
        with TestClient(app) as client:
            uploaded = client.post(
                "/api/knowledge/personal/documents",
                headers={"Idempotency-Key": "agent-personal-rag-test-001"},
                files={"file": ("intro-photolithography.md", content, "text/markdown")},
                data={"metadata": metadata},
            )
            self.assertEqual(uploaded.status_code, 202, uploaded.text)
            document_id = uploaded.json()["document_id"]
            try:
                results = agent_module.search_agent_knowledge(
                    "请介绍光刻技术原理",
                    limit=6,
                    source_types=["personal"],
                )
                self.assertTrue(results)
                self.assertTrue(all(item["source_type"] == "personal" for item in results))
                self.assertEqual(results[0]["document_id"], document_id)
                self.assertEqual(results[0]["source"], "个人知识库")
                self.assertEqual(results[0]["process_steps"], ["LITHO"])
                self.assertTrue(results[0]["reference_id"].startswith("PERSONAL-"))
                self.assertNotIn(
                    "personal",
                    {item["source_type"] for item in search_knowledge("请介绍光刻技术原理", limit=6)},
                )
            finally:
                deleted = client.delete(f"/api/knowledge/personal/documents/{document_id}")
                self.assertEqual(deleted.status_code, 202, deleted.text)

    def test_personal_knowledge_upload_validation_and_token(self):
        with TestClient(app) as client:
            missing_key = client.post(
                "/api/knowledge/personal/documents",
                files={"file": ("note.txt", b"valid text content", "text/plain")},
            )
            self.assertEqual(missing_key.status_code, 422)

            unsupported = client.post(
                "/api/knowledge/personal/documents",
                headers={"Idempotency-Key": "unsupported-file-test"},
                files={"file": ("payload.exe", b"not executable", "application/octet-stream")},
            )
            self.assertEqual(unsupported.status_code, 415)
            self.assertEqual(unsupported.json()["error_code"], "UNSUPPORTED_FILE_TYPE")

            with patch.dict(os.environ, {"FAB_PERSONAL_KNOWLEDGE_API_TOKEN": "private-test-token"}):
                unauthenticated = client.get("/api/knowledge/personal/documents")
                self.assertEqual(unauthenticated.status_code, 401)
                authenticated = client.get(
                    "/api/knowledge/personal/documents",
                    headers={"Authorization": "Bearer private-test-token"},
                )
                self.assertEqual(authenticated.status_code, 200)

    def test_personal_knowledge_scanned_pdf_requires_ocr(self):
        from pypdf import PdfWriter

        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.write(output)
        with TestClient(app) as client:
            uploaded = client.post(
                "/api/knowledge/personal/documents",
                headers={"Idempotency-Key": "ocr-required-test"},
                files={"file": ("scanned.pdf", output.getvalue(), "application/pdf")},
            )
            self.assertEqual(uploaded.status_code, 202, uploaded.text)
            job = client.get(f"/api/knowledge/jobs/{uploaded.json()['job_id']}")
            self.assertEqual(job.status_code, 200)
            self.assertEqual(job.json()["status"], "failed")
            self.assertEqual(job.json()["error"]["error_code"], "OCR_REQUIRED")
            deleted = client.delete(f"/api/knowledge/personal/documents/{uploaded.json()['document_id']}")
            self.assertEqual(deleted.status_code, 202)

    def test_personal_knowledge_office_and_csv_parsers(self):
        from docx import Document
        from openpyxl import Workbook

        docx_buffer = io.BytesIO()
        docx_document = Document()
        docx_document.add_heading("ETCH-01 维护记录", level=1)
        docx_document.add_paragraph("腔体清洗完成，Particle 复测符合要求。")
        docx_document.save(docx_buffer)

        xlsx_buffer = io.BytesIO()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "CVD-02 检查"
        sheet.append(["项目", "结果"])
        sheet.append(["膜厚均匀性", "通过"])
        workbook.save(xlsx_buffer)
        workbook.close()

        samples = (
            ("etch-maintenance.docx", docx_buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "腔体清洗"),
            ("cvd-check.xlsx", xlsx_buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "膜厚均匀性"),
            ("cmp-check.csv", "项目,结果\nPad检查,通过\n".encode("utf-8"), "text/csv", "Pad检查"),
        )
        with TestClient(app) as client:
            for index, (filename, content, mime_type, expected) in enumerate(samples):
                with self.subTest(filename=filename):
                    uploaded = client.post(
                        "/api/knowledge/personal/documents",
                        headers={"Idempotency-Key": f"parser-format-test-{index}"},
                        files={"file": (filename, content, mime_type)},
                    )
                    self.assertEqual(uploaded.status_code, 202, uploaded.text)
                    document_id = uploaded.json()["document_id"]
                    job = client.get(f"/api/knowledge/jobs/{uploaded.json()['job_id']}")
                    self.assertEqual(job.json()["status"], "ready", job.text)
                    parsed = client.get(f"/api/knowledge/personal/documents/{document_id}/content")
                    self.assertIn(expected, " ".join(chunk["content"] for chunk in parsed.json()["chunks"]))
                    self.assertEqual(client.delete(f"/api/knowledge/personal/documents/{document_id}").status_code, 202)

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
            self.assertTrue(response.json()["build"]["version"])

    def test_api_errors_include_correlation_id_and_retry_metadata(self):
        request_id = "req-test-correlation-001"
        with TestClient(app) as client:
            response = client.get("/api/sessions/missing-session", headers={"X-Request-ID": request_id})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers["x-request-id"], request_id)
            self.assertEqual(response.json()["request_id"], request_id)
            self.assertEqual(response.json()["error_code"], "NOT_FOUND")
            self.assertFalse(response.json()["retryable"])

            invalid = client.post("/api/chat/stream", json={"message": "x"})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["error_code"], "VALIDATION_ERROR")
            self.assertTrue(invalid.json()["request_id"])

    def test_unexpected_500_is_structured_without_exposing_traceback(self):
        request_id = "req-internal-error-001"
        with patch("app.main.report_bundle", side_effect=RuntimeError("database secret detail")), TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/reports/dashboard", headers={"X-Request-ID": request_id})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["x-request-id"], request_id)
            self.assertEqual(response.json()["error_code"], "INTERNAL_ERROR")
            self.assertEqual(response.json()["request_id"], request_id)
            self.assertTrue(response.json()["retryable"])
            self.assertNotIn("database secret detail", response.text)

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

    def test_stream_retry_with_same_client_message_id_is_idempotent(self):
        calls = 0

        async def fake_agent(question, history, progress=None):
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

    def test_model_retries_transient_500_before_first_answer_token(self):
        attempts = 0
        progress_events = []
        request = httpx.Request("POST", "https://example.test/chat/completions")
        transient_error = httpx.HTTPStatusError(
            "temporary failure",
            request=request,
            response=httpx.Response(500, request=request),
        )

        async def fake_stream(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise transient_error
            return ({"role": "assistant", "content": "OK"}, {"total_tokens": 3}, "response-test")

        async def progress(event):
            progress_events.append(event)

        settings = SimpleNamespace(
            deepseek_api_key="test-key",
            deepseek_base_url="https://example.test",
            deepseek_model="test-model",
            api_timeout_seconds=5,
            model_max_retries=2,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch("app.agent.asyncio.sleep", new=AsyncMock()),
        ):
            result = asyncio.run(agent_module._run_agent_impl("回复 OK", [], "run-retry-test", progress))
        self.assertEqual(result["answer"], "OK")
        self.assertEqual(attempts, 2)
        self.assertTrue(any(item.get("stage") == "retrying" for item in progress_events))

    def test_retrieved_answer_is_buffered_before_citation_sanitization(self):
        responses = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-search-1",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": '{"query":"CMP"}'},
                }],
            },
            {"role": "assistant", "content": "结论 [来源 KB-999]"},
        ]
        buffer_flags = []
        progress_events = []

        async def fake_stream(*args):
            buffer_flags.append(bool(args[-1].get("buffer_answer")))
            return responses.pop(0), {"total_tokens": 3}, "response-citation-test"

        async def progress(event):
            progress_events.append(event)

        settings = SimpleNamespace(
            deepseek_api_key="test-key",
            deepseek_base_url="https://example.test",
            deepseek_model="test-model",
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        source = {
            "reference_id": "KB-2",
            "source_type": "knowledge",
            "title": "CMP 异常响应",
            "source": "CMP_control_plan.md",
            "section": "原因分析",
        }
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: [source]}),
        ):
            result = asyncio.run(agent_module._run_agent_impl("分析 CMP", [], "run-citation-test", progress))
        self.assertEqual(buffer_flags, [False, True])
        self.assertNotIn("KB-999", result["answer"])
        self.assertIn("[来源 KB-2]", result["answer"])
        answer_events = [item for item in progress_events if item.get("event") == "answer_delta"]
        self.assertEqual("".join(item["delta"] for item in answer_events), result["answer"])

    def test_model_does_not_retry_after_answer_output_starts(self):
        attempts = 0
        request = httpx.Request("POST", "https://example.test/chat/completions")
        stream_error = httpx.HTTPStatusError(
            "stream interrupted",
            request=request,
            response=httpx.Response(500, request=request),
        )

        async def failing_stream(*args):
            nonlocal attempts
            attempts += 1
            args[-1]["answer_emitted"] = True
            raise stream_error

        settings = SimpleNamespace(
            deepseek_api_key="test-key",
            deepseek_base_url="https://example.test",
            deepseek_model="test-model",
            api_timeout_seconds=5,
            model_max_retries=2,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=failing_stream),
            patch("app.agent.asyncio.sleep", new=AsyncMock()),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(agent_module._run_agent_impl("回复 OK", [], "run-no-retry-test"))
        self.assertEqual(attempts, 1)

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
            self.assertEqual(events[-1]["error"]["request_id"], request_id)
            self.assertTrue(events[-1]["error"]["retryable"])
            self.assertTrue(any(
                event.get("event") == "api_stream_error" and event.get("request_id") == request_id
                for event in read_events(200)
            ))
            client.delete(f"/api/sessions/{session_id}/permanent")


if __name__ == "__main__":
    unittest.main()
