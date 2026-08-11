from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.model_health import claim_model_call, get_model_health, record_model_failure, record_model_success


class ModelHealthTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("ATTACH DATABASE ':memory:' AS agent")
        self.connection.executescript("""CREATE TABLE agent.model_catalog(model_id TEXT PRIMARY KEY);
        CREATE TABLE agent.model_health(model_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'unknown',
        consecutive_failures INTEGER NOT NULL DEFAULT 0, opened_at TEXT, open_until TEXT,
        recovery_claimed_at TEXT, last_success_at TEXT, last_failure_at TEXT,
        last_error_category TEXT, updated_at TEXT NOT NULL); INSERT INTO agent.model_catalog VALUES ('a'), ('b');""")
        @contextmanager
        def session():
            yield self.connection
        self.session = session
        self.patcher = patch("app.model_health.db_session", self.session)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.connection.close()

    def test_threshold_open_isolated_and_success_recovers(self):
        for _ in range(2):
            health, transition = record_model_failure("a", "upstream_5xx", threshold=3, cooldown_seconds=60)
            self.assertEqual(health["status"], "degraded")
            self.assertIsNone(transition)
        health, transition = record_model_failure("a", "upstream_5xx", threshold=3, cooldown_seconds=60)
        self.assertEqual((health["status"], transition), ("open", "opened"))
        allowed, _, _ = claim_model_call("a", cooldown_seconds=60, lease_seconds=30)
        self.assertFalse(allowed)
        self.assertEqual(get_model_health("b")["status"], "unknown")
        self.connection.execute("UPDATE agent.model_health SET open_until='2000-01-01T00:00:00+00:00' WHERE model_id='a'")
        self.connection.commit()
        allowed, health, transition = claim_model_call("a", cooldown_seconds=60, lease_seconds=30)
        self.assertTrue(allowed)
        self.assertEqual((health["status"], transition), ("half_open", "recovery_started"))
        allowed, _, _ = claim_model_call("a", cooldown_seconds=60, lease_seconds=30)
        self.assertFalse(allowed)
        health, transition = record_model_success("a")
        self.assertEqual((health["status"], health["consecutive_failures"], transition), ("healthy", 0, "recovered"))

    def test_half_open_failure_reopens_and_stale_lease_is_reclaimed(self):
        record_model_failure("a", "network", threshold=1, cooldown_seconds=1)
        self.connection.execute("UPDATE agent.model_health SET open_until='2000-01-01T00:00:00+00:00' WHERE model_id='a'")
        self.connection.commit()
        allowed, health, transition = claim_model_call("a", cooldown_seconds=1, lease_seconds=30)
        self.assertTrue(allowed)
        self.assertEqual(health["status"], "half_open")
        self.assertEqual(transition, "recovery_started")
        health, transition = record_model_failure("a", "timeout", threshold=3, cooldown_seconds=60)
        self.assertEqual(health["status"], "open")
        self.assertEqual(transition, "opened")
        self.connection.execute("UPDATE agent.model_health SET open_until='2000-01-01T00:00:00+00:00', recovery_claimed_at='2000-01-01T00:00:00+00:00', status='half_open' WHERE model_id='a'")
        self.connection.commit()
        allowed, health, transition = claim_model_call("a", cooldown_seconds=60, lease_seconds=1)
        self.assertTrue(allowed)
        self.assertEqual(health["status"], "half_open")
        self.assertEqual(transition, "recovery_reclaimed")

    def test_unknown_and_healthy_calls_are_allowed(self):
        allowed, health, transition = claim_model_call("a", cooldown_seconds=60, lease_seconds=30)
        self.assertTrue(allowed)
        self.assertEqual(health["status"], "unknown")
        self.assertIsNone(transition)
        record_model_success("a")
        allowed, health, transition = claim_model_call("a", cooldown_seconds=60, lease_seconds=30)
        self.assertTrue(allowed)
        self.assertEqual(health["status"], "healthy")
        self.assertIsNone(transition)

    def test_only_safe_category_is_persisted(self):
        health, _ = record_model_failure("a", "https://secret.example/response body", threshold=3, cooldown_seconds=60)
        self.assertEqual(health["last_error_category"], "network")
        values = tuple(self.connection.execute("SELECT * FROM agent.model_health WHERE model_id='a'").fetchone())
        self.assertNotIn("secret.example", " ".join(str(value) for value in values if value))
