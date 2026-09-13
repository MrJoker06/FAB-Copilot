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
    def test_canonical_exports_have_gateway_owners_and_removed_roots(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        for name in ("model_registry", "model_compatibility", "model_health", "model_streaming"):
            self.assertFalse((root / f"{name}.py").exists())
        owners = (
            (registry.publish_model, "app.model_gateway.registry"),
            (compatibility.ModelCompatibilityError, "app.model_gateway.compatibility"),
            (compatibility.provider_request_options, "app.model_gateway.compatibility"),
            (streaming.stream_completion, "app.model_gateway.streaming"),
            (streaming.retryable_model_error, "app.model_gateway.streaming"),
        )
        for value, owner in owners:
            self.assertEqual(value.__module__, owner)

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
                self.assertEqual(str(inspect.signature(getattr(health, name))), signature)

    def test_canonical_health_resolves_live_session_per_call_and_bypasses_for_explicit_connection(self):
        first_connection, second_connection = _connection(), _connection()
        first_calls, second_calls = [], []
        first_factory = _factory(first_connection, first_calls)
        second_factory = _factory(second_connection, second_calls)
        original_factory = health.db_session
        try:
            with patch.object(health, "db_session", first_factory):
                health.ensure_model_health("first")
            with patch.object(health, "db_session", second_factory):
                health.ensure_model_health("second")
                before = len(second_calls)
                health.ensure_model_health("explicit", second_connection)
                self.assertEqual(len(second_calls), before)
                health.get_model_health("get")
                health.claim_model_call("claim", cooldown_seconds=60, lease_seconds=30)
                health.record_model_success("success")
                health.record_model_failure("failure", "network", threshold=1, cooldown_seconds=60)
            self.assertEqual(first_calls, ["opened"])
            self.assertEqual(second_calls, ["opened"] * 5)
            self.assertIs(health.db_session, original_factory)
            self.assertEqual({row[0] for row in first_connection.execute("SELECT model_id FROM agent.model_health")}, {"first"})
            self.assertEqual(
                {row[0] for row in second_connection.execute("SELECT model_id FROM agent.model_health")},
                {"second", "explicit", "get", "claim", "success", "failure"},
            )
        finally:
            first_connection.close()
            second_connection.close()

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
            "gateway_first": "import app.model_gateway.registry; import app.model_gateway.compatibility; import app.model_gateway.health; import app.model_gateway.streaming; import app.persistence.database",
            "persistence_first": "import app.persistence.database; import app.model_gateway.streaming; import app.model_gateway.health; import app.model_gateway.compatibility; import app.model_gateway.registry",
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
