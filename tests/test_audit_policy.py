from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import audit


NOW = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


class LogContentPolicyTests(unittest.TestCase):
    def policy(self, **environment):
        values = {"AGENT_LOG_CONTENT": "metadata", "AGENT_LOG_FULL_TEST_MODE": "", "AGENT_LOG_FULL_EXPIRES_AT": "", **environment}
        with patch.dict(os.environ, values, clear=False):
            return audit.log_content_policy(NOW, started_at=NOW)

    def test_metadata_and_redacted_requests_remain_compatible(self):
        self.assertEqual(self.policy()["effective_mode"], "metadata")
        invalid = self.policy(AGENT_LOG_CONTENT="unexpected")
        self.assertEqual((invalid["requested_mode"], invalid["effective_mode"]), ("metadata", "metadata"))
        redacted = self.policy(AGENT_LOG_CONTENT="redacted")
        self.assertEqual((redacted["effective_mode"], redacted["reason"]), ("redacted", "requested_redacted"))

    def test_full_requires_test_switch_and_valid_bounded_expiry(self):
        cases = [
            ({"AGENT_LOG_CONTENT": "full"}, "test_mode_disabled"),
            ({"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "yes"}, "expiry_missing"),
            ({"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "on", "AGENT_LOG_FULL_EXPIRES_AT": "nope"}, "expiry_invalid"),
            ({"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": "2026-08-20T09:00:00"}, "expiry_naive"),
            ({"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "1", "AGENT_LOG_FULL_EXPIRES_AT": "2026-08-20T08:00:00Z"}, "expiry_expired"),
            ({"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": "2026-08-21T08:00:01Z"}, "expiry_exceeds_max_duration"),
        ]
        for environment, reason in cases:
            with self.subTest(reason=reason):
                policy = self.policy(**environment)
                self.assertEqual(policy["effective_mode"], "metadata")
                self.assertEqual(policy["reason"], reason)

    def test_valid_full_policy_normalizes_utc_and_transitions_without_reload(self):
        expires_at = NOW + timedelta(minutes=30)
        with patch.dict(os.environ, {"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": expires_at.isoformat()}, clear=False):
            active = audit.log_content_policy(NOW, started_at=NOW)
            expired = audit.log_content_policy(expires_at, started_at=NOW)
        self.assertEqual(active["effective_mode"], "full")
        self.assertEqual(active["expires_at"], "2026-08-20T08:30:00Z")
        self.assertEqual(active["remaining_seconds"], 1800)
        self.assertEqual((expired["effective_mode"], expired["reason"]), ("metadata", "expiry_expired"))

    def test_max_duration_is_anchored_to_service_start(self):
        exact_boundary = NOW + timedelta(hours=24)
        too_far = NOW + timedelta(hours=26)
        with patch.dict(os.environ, {"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": too_far.isoformat()}, clear=False):
            initial = audit.log_content_policy(NOW, started_at=NOW)
            later = audit.log_content_policy(NOW + timedelta(hours=3), started_at=NOW)
        self.assertEqual((initial["effective_mode"], initial["reason"]), ("metadata", "expiry_exceeds_max_duration"))
        self.assertEqual((later["effective_mode"], later["reason"]), ("metadata", "expiry_exceeds_max_duration"))
        with patch.dict(os.environ, {"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": exact_boundary.isoformat()}, clear=False):
            active = audit.log_content_policy(NOW + timedelta(hours=23), started_at=NOW)
            expired = audit.log_content_policy(exact_boundary, started_at=NOW)
        self.assertEqual(active["effective_mode"], "full")
        self.assertEqual((expired["effective_mode"], expired["reason"]), ("metadata", "expiry_expired"))

    def test_emit_final_guard_redacts_credentials_and_drops_full_content_after_expiry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(audit, "RUN_LOG_DIR", Path(directory)), patch.object(audit, "_logger"), patch.object(audit, "utc_now", return_value="2026-08-20T08:00:00Z"):
            expiry = NOW + timedelta(minutes=1)
            active_policy = {"effective_mode": "full", "requested_mode": "full", "status": "active", "reason": "full_test_window_active", "full_test_mode": True, "expires_at": "2026-08-20T08:01:00Z", "remaining_seconds": 60, "max_duration_hours": 24}
            expired_policy = {**active_policy, "effective_mode": "metadata", "status": "fallback", "reason": "expiry_expired", "remaining_seconds": 0}
            with patch.dict(os.environ, {"AGENT_LOG_CONTENT": "full", "AGENT_LOG_FULL_TEST_MODE": "true", "AGENT_LOG_FULL_EXPIRES_AT": expiry.isoformat()}, clear=False), patch.object(audit, "log_content_policy", side_effect=[active_policy, expired_policy]):
                audit.emit("test", "run-policy", full_content={"question": "private", "authorization": "secret"})
                audit.emit("test", "run-policy", full_content={"question": "must-drop"})
            lines = (Path(directory) / "2026-08-20" / "run-policy.jsonl").read_text(encoding="utf-8").splitlines()
        active, expired = [json.loads(line) for line in lines]
        self.assertEqual(active["question"], "private")
        self.assertEqual(active["authorization"], "<redacted>")
        self.assertEqual(active["content_mode"], "full")
        self.assertNotIn("question", expired)
        self.assertEqual(expired["content_mode"], "metadata")

    def test_emit_reserves_audit_schema_and_keeps_component_schema_separate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(audit, "RUN_LOG_DIR", Path(directory)), patch.object(audit, "_logger"), patch.object(audit, "utc_now", return_value="2026-08-23T08:00:00Z"):
            audit.emit(
                "turn_decision_created",
                "run-schema",
                schema_version="component-must-not-win",
                turn_decision_schema_version="1.0",
            )
            line = (Path(directory) / "2026-08-23" / "run-schema.jsonl").read_text(encoding="utf-8")
        event = json.loads(line)
        self.assertEqual(event["schema_version"], audit.SCHEMA_VERSION)
        self.assertEqual(event["audit_schema_version"], audit.SCHEMA_VERSION)
        self.assertEqual(event["turn_decision_schema_version"], "1.0")

    def test_legacy_trace_fields_are_normalized_without_rewriting_history(self):
        decision = audit.normalize_audit_event({
            "event": "turn_decision_created", "schema_version": "1.0", "run_id": "legacy",
        })
        self.assertEqual(decision["schema_version"], "1.0")
        self.assertEqual(decision["audit_schema_version"], "legacy")
        self.assertEqual(decision["turn_decision_schema_version"], "1.0")
        finished = audit.normalize_audit_event({
            "event": "agent_run_finished", "schema_version": "1.3", "source_count": 2,
        })
        self.assertEqual(finished["audit_schema_version"], "1.3")
        self.assertEqual(finished["knowledge_source_count"], 2)
        self.assertEqual(finished["tool_evidence_count"], 0)
        self.assertEqual(finished["total_reference_count"], 2)

    def test_access_events_stay_in_aggregate_without_per_request_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(audit, "RUN_LOG_DIR", Path(directory)), patch.object(audit, "_logger") as logger, patch.object(audit, "utc_now", return_value="2026-08-20T08:00:00Z"):
            audit.emit("api_request_started", "req-admin-poll", path="/api/admin/overview")
            audit.emit("api_request_finished", "req-admin-poll", path="/api/admin/overview")
            audit.emit("api_stream_error", "req-stream", error_type="MODEL_NETWORK_ERROR")
            audit.emit("agent_run_started", "run-agent")
            day = Path(directory) / "2026-08-20"
            self.assertFalse((day / "req-admin-poll.jsonl").exists())
            self.assertTrue((day / "req-stream.jsonl").exists())
            self.assertTrue((day / "run-agent.jsonl").exists())
            self.assertEqual(logger.info.call_count, 4)

    def test_monitoring_summary_accepts_legacy_events_and_counts_degradation(self):
        now = datetime.now(timezone.utc)
        legacy_at = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        failure_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        degraded_at = now.isoformat().replace("+00:00", "Z")
        events = [
            {"timestamp": legacy_at, "event": "agent_run_finished", "status": "success", "run_id": "legacy"},
            {"timestamp": failure_at, "event": "question_context_resolution_failed", "failure_reason": "timeout", "run_id": "degraded"},
            {"timestamp": degraded_at, "event": "agent_run_finished", "status": "success", "outcome": "degraded", "degraded": True, "run_id": "degraded"},
            {"timestamp": degraded_at, "event": "model_call_finished", "phase": "contextualization", "duration_ms": 40},
            {"timestamp": degraded_at, "event": "model_call_finished", "phase": "contextualization", "duration_ms": 80},
            {"timestamp": degraded_at, "event": "stream_delivery_summary", "first_answer_ms": 20},
            {"timestamp": degraded_at, "event": "stream_delivery_summary", "first_answer_ms": 60},
        ]
        with patch.object(audit, "read_events", return_value=events), patch.object(audit, "log_content_policy", return_value={}):
            summary = audit.monitoring_summary(hours=24)
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["degraded_run_count"], 1)
        self.assertEqual(summary["completed_run_count"], 1)
        self.assertEqual(summary["context_timeout_count"], 1)
        self.assertEqual(summary["contextualization_duration_p50_ms"], 40.0)
        self.assertEqual(summary["contextualization_duration_p95_ms"], 80.0)
        self.assertEqual(summary["first_answer_p50_ms"], 20.0)
        self.assertEqual(summary["first_answer_p95_ms"], 60.0)
        self.assertEqual(summary["recent_degraded_runs"][0]["run_id"], "degraded")

    def test_monitoring_summary_exposes_six_named_run_stage_durations(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = [
            {"timestamp": now, "event": "context_stage_completed", "run_id": "run-stages", "duration_ms": 11},
            {"timestamp": now, "event": "routing_stage_completed", "run_id": "run-stages", "duration_ms": 12},
            {"timestamp": now, "event": "knowledge_retrieval_decided", "run_id": "run-stages", "duration_ms": 13},
            {"timestamp": now, "event": "model_call_finished", "run_id": "run-stages", "phase": "ready_plan_synthesis", "duration_ms": 14},
            {"timestamp": now, "event": "stream_delivery_summary", "run_id": "run-stages", "answer_stream_duration_ms": 15},
            {
                "timestamp": now, "event": "agent_run_finished", "run_id": "run-stages",
                "status": "success", "tool_duration_ms": 16, "retrieval_duration_ms": 13,
                "knowledge_source_count": 2, "tool_evidence_count": 3, "total_reference_count": 5,
            },
        ]
        with patch.object(audit, "read_events", return_value=events), patch.object(audit, "log_content_policy", return_value={}):
            summary = audit.monitoring_summary(hours=24)
        stages = summary["recent_runs"][0]["stage_durations_ms"]
        self.assertEqual(stages, {
            "context": 11.0, "routing": 12.0, "retrieval": 13.0,
            "tools": 16.0, "synthesis": 14.0, "stream": 15.0,
        })
        self.assertEqual(set(summary["stage_durations"]), set(audit.TRACE_STAGES))
        self.assertEqual(summary["stage_durations"]["synthesis"]["p95_ms"], 14.0)
