from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import MODEL_CAPABILITIES_SCHEMA_VERSION, MODEL_COMPATIBILITY_SCHEMA_VERSION, MODEL_HEALTH_SCHEMA_VERSION, _migrate_model_catalog_capabilities, _migrate_model_catalog_compatibility, _migrate_model_health
from app.model_registry import MODEL_CAPABILITY_DEFAULTS, _decode_model, normalize_capabilities


class ModelCapabilitiesTests(unittest.TestCase):
    def test_normalization_keeps_extensions_and_fills_legacy_contract(self):
        result = normalize_capabilities({"streaming": False, "vendor_mode": "beta"})
        self.assertEqual(result, {
            "streaming": False, "tool_calls": True, "thinking": False,
            "native_multimodal": False, "vendor_mode": "beta",
        })

    def test_decode_handles_invalid_and_non_object_json(self):
        row = {"status": "published", "capabilities_json": "[1, 2]"}
        self.assertEqual(_decode_model(row)["capabilities"], MODEL_CAPABILITY_DEFAULTS)
        self.assertEqual(_decode_model({"status": "published", "capabilities_json": "{"})["capabilities"], MODEL_CAPABILITY_DEFAULTS)

    def test_migration_is_idempotent_and_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE model_catalog (model_id TEXT PRIMARY KEY, capabilities_json TEXT NOT NULL)")
            connection.executemany("INSERT INTO model_catalog VALUES (?, ?)", [
                ("legacy", '{"streaming":false,"tool_calls":true,"vendor":"x"}'),
                ("damaged", "not-json"),
                ("array", "[]"),
            ])
            _migrate_model_catalog_capabilities(connection)
            connection.commit()
            first = dict(connection.execute("SELECT model_id, capabilities_json FROM model_catalog").fetchall())
            connection.close()
            connection = sqlite3.connect(path)
            _migrate_model_catalog_capabilities(connection)
            connection.commit()
            second = dict(connection.execute("SELECT model_id, capabilities_json FROM model_catalog").fetchall())
            migration = connection.execute("SELECT version FROM schema_migrations WHERE version = 10").fetchone()
            connection.close()
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first["legacy"]), {
            "streaming": False, "tool_calls": True, "thinking": False,
            "native_multimodal": False, "vendor": "x",
        })
        self.assertEqual(json.loads(first["damaged"]), MODEL_CAPABILITY_DEFAULTS)
        self.assertEqual(json.loads(first["array"]), MODEL_CAPABILITY_DEFAULTS)
        self.assertEqual(MODEL_CAPABILITIES_SCHEMA_VERSION, 10)
        self.assertEqual(migration[0], 10)

    def test_compatibility_migration_is_additive_and_preserves_v10(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE model_catalog (model_id TEXT PRIMARY KEY, capabilities_json TEXT NOT NULL)")
        connection.execute("INSERT INTO model_catalog VALUES ('old', '{}')")
        _migrate_model_catalog_capabilities(connection)
        _migrate_model_catalog_compatibility(connection)
        _migrate_model_health(connection)
        _migrate_model_health(connection)
        _migrate_model_catalog_compatibility(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(model_catalog)")}
        rows = dict(connection.execute("SELECT version, description FROM schema_migrations"))
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.close()
        self.assertIn("compatibility_json", columns)
        self.assertIn("compatibility_checked_at", columns)
        self.assertIn("model_health", tables)
        self.assertEqual(rows[MODEL_CAPABILITIES_SCHEMA_VERSION], "model catalog capabilities")
        self.assertEqual(rows[MODEL_COMPATIBILITY_SCHEMA_VERSION], "model publication compatibility")
        self.assertEqual(rows[MODEL_HEALTH_SCHEMA_VERSION], "model circuit health")
