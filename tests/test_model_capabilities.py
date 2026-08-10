from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import MODEL_CAPABILITIES_SCHEMA_VERSION, _migrate_model_catalog_capabilities
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
