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
