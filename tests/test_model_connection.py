from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from app.config import ModelConnection, get_settings


MODEL_ENVIRONMENT = {
    "FAB_MODEL_PROVIDER",
    "FAB_MODEL_API_KEY",
    "FAB_MODEL_BASE_URL",
    "FAB_MODEL_NAME",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "MODEL_CONTEXT_TIMEOUT_MS",
}


class ModelConnectionTests(unittest.TestCase):
    def _environment(self, values: dict[str, str]):
        clean = {key: value for key, value in os.environ.items() if key not in MODEL_ENVIRONMENT}
        clean.update(values)
        return patch.dict(os.environ, clean, clear=True)

    def test_generic_variables_take_precedence(self):
        with self._environment({
            "FAB_MODEL_PROVIDER": " OpenAI-Compatible ",
            "FAB_MODEL_API_KEY": "generic-secret",
            "FAB_MODEL_BASE_URL": "https://generic.example/v1/",
            "FAB_MODEL_NAME": "generic-model",
            "DEEPSEEK_API_KEY": "legacy-secret",
            "DEEPSEEK_BASE_URL": "https://legacy.example",
            "DEEPSEEK_MODEL": "deepseekv4-pro",
        }):
            connection = get_settings().model_connection
        self.assertEqual(connection.provider, "openai-compatible")
        self.assertEqual(connection.api_key, "generic-secret")
        self.assertEqual(connection.base_url, "https://generic.example/v1")
        self.assertEqual(connection.model, "generic-model")

    def test_legacy_variables_remain_fallbacks_with_alias_support(self):
        with self._environment({
            "DEEPSEEK_API_KEY": "legacy-secret",
            "DEEPSEEK_BASE_URL": "https://legacy.example/",
            "DEEPSEEK_MODEL": "deepseekv4-pro",
        }):
            connection = get_settings().model_connection
        self.assertEqual(connection.provider, "deepseek")
        self.assertEqual(connection.api_key, "legacy-secret")
        self.assertEqual(connection.base_url, "https://legacy.example")
        self.assertEqual(connection.model, "deepseek-v4-pro")

    def test_blank_base_url_falls_back_to_the_default(self):
        with self._environment({"FAB_MODEL_BASE_URL": "   ", "DEEPSEEK_BASE_URL": ""}):
            connection = get_settings().model_connection
        self.assertEqual(connection.base_url, "https://api.deepseek.com")

    def test_connection_is_immutable_and_repr_redacts_api_key(self):
        connection = ModelConnection("deepseek", "must-not-appear", "https://example.test", "model")
        with self.assertRaises(FrozenInstanceError):
            connection.model = "other"
        self.assertNotIn("must-not-appear", repr(connection))

    def test_context_timeout_uses_default_and_clamps_milliseconds(self):
        with self._environment({}):
            self.assertEqual(get_settings().model_context_timeout_seconds, 15.0)
        with self._environment({"MODEL_CONTEXT_TIMEOUT_MS": "1000"}):
            self.assertEqual(get_settings().model_context_timeout_seconds, 1.0)
        with self._environment({"MODEL_CONTEXT_TIMEOUT_MS": "60000"}):
            self.assertEqual(get_settings().model_context_timeout_seconds, 60.0)
        with self._environment({"MODEL_CONTEXT_TIMEOUT_MS": "10"}):
            self.assertEqual(get_settings().model_context_timeout_seconds, 1.0)
        with self._environment({"MODEL_CONTEXT_TIMEOUT_MS": "999999"}):
            self.assertEqual(get_settings().model_context_timeout_seconds, 60.0)


if __name__ == "__main__":
    unittest.main()
