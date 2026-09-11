from __future__ import annotations

import inspect
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import model_compatibility, model_health, model_registry, model_streaming
from app.model_gateway import compatibility, health, registry, streaming


@contextmanager
def _session(connection):
    yield connection


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("ATTACH DATABASE ':memory:' AS agent")
    connection.executescript("""CREATE TABLE agent.model_health(model_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'unknown', consecutive_failures INTEGER NOT NULL DEFAULT 0,
        opened_at TEXT, open_until TEXT, recovery_claimed_at TEXT, last_success_at TEXT,
        last_failure_at TEXT, last_error_category TEXT, updated_at TEXT NOT NULL);""")
    return connection


def _factory(connection, calls):
    @contextmanager
    def session():
        calls.append("opened")
        yield connection

    return session


class ModelGatewayModuleBoundaryTests(unittest.TestCase):
    def test_facades_retain_non_health_public_object_identity(self):
        self.assertIs(model_registry.publish_model, registry.publish_model)
        self.assertIs(model_registry.MODEL_CAPABILITY_DEFAULTS, registry.MODEL_CAPABILITY_DEFAULTS)
        self.assertIs(model_compatibility.ModelCompatibilityError, compatibility.ModelCompatibilityError)
        self.assertIs(model_compatibility.provider_request_options, compatibility.provider_request_options)
        self.assertIs(model_streaming.stream_completion, streaming.stream_completion)
        self.assertIs(model_streaming.retryable_model_error, streaming.retryable_model_error)

    def test_health_wrapper_signatures_preserve_the_original_public_contract(self):
        expected = {
            "ensure_model_health": "(model_id: 'str', connection=None) -> 'None'",
            "get_model_health": "(model_id: 'str') -> 'dict'",
            "claim_model_call": "(model_id: 'str', *, cooldown_seconds: 'int', lease_seconds: 'int') -> 'tuple[bool, dict, str | None]'",
            "record_model_success": "(model_id: 'str') -> 'tuple[dict, str | None]'",
            "record_model_failure": "(model_id: 'str', category: 'str', *, threshold: 'int', cooldown_seconds: 'int') -> 'tuple[dict, str | None]'",
        }
        for name, signature in expected.items():
            with self.subTest(name=name):
                self.assertEqual(str(inspect.signature(getattr(model_health, name))), signature)
                self.assertEqual(str(inspect.signature(getattr(health, name))), signature)

    def test_old_and_canonical_health_patch_points_are_independent_and_live(self):
        legacy_connection, canonical_connection = _connection(), _connection()
        legacy_calls, canonical_calls = [], []
        legacy_factory = _factory(legacy_connection, legacy_calls)
        canonical_factory = _factory(canonical_connection, canonical_calls)
        original_legacy_factory, original_canonical_factory = model_health.db_session, health.db_session
        try:
            with patch.object(model_health, "db_session", legacy_factory), patch.object(health, "db_session", canonical_factory):
                model_health.ensure_model_health("legacy-own")
                health.ensure_model_health("canonical-own")
                legacy_before, canonical_before = len(legacy_calls), len(canonical_calls)
                model_health.ensure_model_health("legacy-supplied", legacy_connection)
                health.ensure_model_health("canonical-supplied", canonical_connection)
                self.assertEqual((len(legacy_calls), len(canonical_calls)), (legacy_before, canonical_before))
                self.assertIs(model_health.db_session, legacy_factory)
                self.assertIs(health.db_session, canonical_factory)
                self.assertIs(model_health._canonical.db_session, canonical_factory)

                model_health.get_model_health("legacy-get")
                model_health.claim_model_call("legacy-claim", cooldown_seconds=60, lease_seconds=30)
                model_health.record_model_success("legacy-success")
                model_health.record_model_failure("legacy-failure", "network", threshold=1, cooldown_seconds=60)
                health.get_model_health("canonical-get")
                health.claim_model_call("canonical-claim", cooldown_seconds=60, lease_seconds=30)
                health.record_model_success("canonical-success")
                health.record_model_failure("canonical-failure", "network", threshold=1, cooldown_seconds=60)
                self.assertIs(model_health.db_session, legacy_factory)
                self.assertIs(health.db_session, canonical_factory)
                self.assertIsNot(model_health.db_session, health.db_session)
            self.assertIs(model_health.db_session, original_legacy_factory)
            self.assertIs(health.db_session, original_canonical_factory)
            self.assertEqual(len(legacy_calls), 5)
            self.assertEqual(len(canonical_calls), 5)
            self.assertEqual(
                {row[0] for row in legacy_connection.execute("SELECT model_id FROM agent.model_health")},
                {"legacy-own", "legacy-supplied", "legacy-get", "legacy-claim", "legacy-success", "legacy-failure"},
            )
            self.assertEqual(
                {row[0] for row in canonical_connection.execute("SELECT model_id FROM agent.model_health")},
                {"canonical-own", "canonical-supplied", "canonical-get", "canonical-claim", "canonical-success", "canonical-failure"},
            )
        finally:
            legacy_connection.close()
            canonical_connection.close()

    def test_canonical_health_circuit_recovery_contract(self):
        connection = _connection()
        try:
            with patch.object(health, "db_session", lambda: _session(connection)):
                health.record_model_failure("model", "timeout", threshold=1, cooldown_seconds=1)
                connection.execute("UPDATE agent.model_health SET open_until='2000-01-01T00:00:00+00:00' WHERE model_id='model'")
                connection.commit()
                allowed, current, transition = health.claim_model_call("model", cooldown_seconds=1, lease_seconds=30)
                self.assertEqual((allowed, current["status"], transition), (True, "half_open", "recovery_started"))
                current, transition = health.record_model_success("model")
            self.assertEqual((current["status"], transition), ("healthy", "recovered"))
        finally:
            connection.close()

    def test_import_orders_do_not_probe_providers(self):
        orders = {
            "canonical_first": "import app.persistence.database; import app.model_gateway.registry; import app.model_gateway.compatibility; import app.model_gateway.health; import app.model_gateway.streaming; import app.model_registry; import app.model_compatibility; import app.model_health; import app.model_streaming",
            "legacy_first": "import app.persistence.database; import app.model_registry; import app.model_compatibility; import app.model_health; import app.model_streaming; import app.model_gateway.registry; import app.model_gateway.compatibility; import app.model_gateway.health; import app.model_gateway.streaming",
        }
        guard = "import httpx, socket; blocked=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('provider networking during import')); socket.socket.connect=blocked; httpx.Client.send=blocked; httpx.AsyncClient.send=blocked; "
        for name, imports in orders.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, "-c", guard + imports + "; print('import-ok')"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env={**os.environ, "AGENT_LOG_PATH": f"{directory}/events.jsonl", "AGENT_RUN_LOG_DIR": f"{directory}/runs"},
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "import-ok")


if __name__ == "__main__":
    unittest.main()
