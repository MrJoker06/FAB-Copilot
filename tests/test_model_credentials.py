from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.model_credentials import (
    ModelCredentialError,
    clear_stored_model_api_key,
    credential_status,
    get_stored_model_api_key,
    model_credentials_path,
    resolve_model_api_key,
    set_stored_model_api_key,
)
from app.core.settings import PROJECT_DIR


class ModelCredentialStoreTests(unittest.TestCase):
    def _environment(self, directory: str, **values: str):
        clean = {key: value for key, value in os.environ.items() if not key.startswith("FAB_MODEL") and key != "DEEPSEEK_API_KEY"}
        clean["FAB_MODEL_CREDENTIALS_PATH"] = str(Path(directory) / "model_credentials.json")
        clean.update(values)
        return patch.dict(os.environ, clean, clear=True)

    def test_local_entry_is_authoritative_for_its_model(self):
        with tempfile.TemporaryDirectory() as directory, self._environment(directory):
            set_stored_model_api_key("qwen38-27b-q4km", "local-secret")
            self.assertEqual(get_stored_model_api_key("qwen38-27b-q4km"), "local-secret")
            self.assertEqual(resolve_model_api_key("qwen38-27b-q4km", "openai-compatible"), "local-secret")
            self.assertEqual(credential_status("qwen38-27b-q4km", "openai-compatible"), (True, "local_file"))
            # Another model must not borrow the stored credential.
            self.assertEqual(resolve_model_api_key("deepseekv4-flash", "deepseek"), "")

    def test_clear_falls_back_to_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            with self._environment(directory, FAB_MODEL_API_KEY="environment-secret"):
                set_stored_model_api_key("deepseekv4-flash", "local-secret")
                self.assertTrue(clear_stored_model_api_key("deepseekv4-flash"))
                self.assertEqual(resolve_model_api_key("deepseekv4-flash", "deepseek"), "environment-secret")
                self.assertEqual(credential_status("deepseekv4-flash", "deepseek"), (True, "environment"))
                self.assertFalse(clear_stored_model_api_key("deepseekv4-flash"))

    def test_missing_file_is_empty_and_not_created(self):
        with tempfile.TemporaryDirectory() as directory, self._environment(directory):
            self.assertIsNone(get_stored_model_api_key("qwen38-27b-q4km"))
            self.assertEqual(credential_status("qwen38-27b-q4km", "openai-compatible"), (False, "missing"))
            self.assertFalse(model_credentials_path().exists())

    def test_store_rejects_empty_multiline_and_oversized_keys(self):
        with tempfile.TemporaryDirectory() as directory, self._environment(directory):
            for value in ("", "   ", "line-one\nline-two", "x" * 4097):
                with self.assertRaises(ModelCredentialError):
                    set_stored_model_api_key("qwen38-27b-q4km", value)
            self.assertFalse(model_credentials_path().exists())

    def test_corrupt_store_is_reported_without_losing_the_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self._environment(directory):
                path = model_credentials_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{not-json", encoding="utf-8")
                with self.assertRaises(ModelCredentialError):
                    get_stored_model_api_key("qwen38-27b-q4km")
                self.assertEqual(path.read_text(encoding="utf-8"), "{not-json")

    def test_write_is_atomic_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory, self._environment(directory):
            set_stored_model_api_key("model-a", "first")
            set_stored_model_api_key("model-b", "second")
            payload = json.loads(model_credentials_path().read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(sorted(payload["credentials"]), ["model-a", "model-b"])
            self.assertEqual(list(model_credentials_path().parent.glob(".model-credentials-*")), [])

    def test_relative_path_resolves_against_project_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            with self._environment(directory):
                os.environ["FAB_MODEL_CREDENTIALS_PATH"] = "relative/credentials.json"
                self.assertEqual(
                    model_credentials_path(),
                    PROJECT_DIR / "relative/credentials.json",
                )
