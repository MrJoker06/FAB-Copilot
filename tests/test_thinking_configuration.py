from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.local_model_config import (
    get_local_model,
    local_models_path,
    remove_local_model,
    save_local_model,
    update_local_model_capabilities,
)
from app.core.model_capabilities import (
    normalize_capability_declaration,
    thinking_settings,
)
from app.model_gateway.compatibility import provider_request_options
from app.model_gateway.registry import _decode_model


class ThinkingConfigurationTests(unittest.TestCase):
    def test_thinking_settings_use_declared_defaults_and_visibility(self):
        capabilities = {
            "thinking": True,
            "thinking_effort": "low",
            "thinking_effort_options": ["low", "xhigh"],
            "reasoning_dialect": "qwen",
        }
        settings = thinking_settings(
            capabilities, provider="openai-compatible", provider_model="Qwen3.8-27B"
        )
        self.assertEqual(
            settings,
            {
                "thinking": True,
                "effort": "low",
                "options": ["low", "xhigh"],
                "dialect": "qwen",
            },
        )

    def test_thinking_disabled_forces_off_and_clears_options(self):
        declaration = normalize_capability_declaration(
            {
                "thinking": False,
                "thinking_effort": "high",
                "thinking_effort_options": ["high"],
                "reasoning_dialect": "qwen",
            }
        )
        self.assertEqual(declaration["thinking_effort"], "off")
        self.assertEqual(declaration["thinking_effort_options"], [])

    def test_thinking_requires_at_least_one_visible_option(self):
        with self.assertRaisesRegex(ValueError, "至少选择一个思考档位"):
            normalize_capability_declaration(
                {
                    "thinking": True,
                    "thinking_effort": "off",
                    "thinking_effort_options": [],
                },
                provider="openai-compatible",
                provider_model="Qwen3.8-27B",
            )

    def test_qwen_uses_template_kwargs_and_maps_high_to_xhigh(self):
        self.assertEqual(
            provider_request_options(
                "openai-compatible", True, "high", "Qwen3.8-27B", "qwen"
            ),
            {
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "reasoning_effort": "xhigh",
                }
            },
        )

    def test_deepseek_uses_thinking_objects(self):
        self.assertEqual(
            provider_request_options("deepseek", True, "medium", "deepseek-v4", "deepseek"),
            {"thinking": {"type": "enabled"}, "reasoning_effort": "medium"},
        )
        self.assertEqual(
            provider_request_options("deepseek", False),
            {"thinking": {"type": "disabled"}},
        )


class LocalModelConfigTests(unittest.TestCase):
    def test_round_trip_and_decode_overlay(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"FAB_LOCAL_MODELS_PATH": str(Path(temporary) / "models.json")}
        ):
            path = local_models_path()
            save_local_model(
                "local-test",
                display_name="Local Test",
                provider="openai-compatible",
                provider_model="local-test-v1",
                base_url="http://127.0.0.1:8080/v1",
                capabilities={"thinking": True, "thinking_effort": "low"},
            )
            self.assertTrue(path.exists())
            stored = get_local_model("local-test")
            self.assertEqual(stored["display_name"], "Local Test")
            self.assertEqual(stored["base_url"], "http://127.0.0.1:8080/v1")

            row = {
                "model_id": "local-test",
                "display_name": "Database Name",
                "provider": "openai-compatible",
                "provider_model": "db-model",
                "base_url": "https://database.invalid",
                "status": "published",
                "capabilities_json": '{"thinking": false}',
            }
            with patch(
                "app.model_gateway.registry.credential_status",
                return_value=(False, "missing"),
            ):
                decoded = _decode_model(dict(row))
                self.assertEqual(decoded["display_name"], "Local Test")
                self.assertEqual(decoded["provider_model"], "local-test-v1")
                self.assertEqual(decoded["config_source"], "local_file")
                self.assertTrue(decoded["capabilities"]["thinking"])

                update_local_model_capabilities(
                    "local-test",
                    {"thinking": True, "thinking_effort": "xhigh"},
                )
                updated = _decode_model(dict(row))
                self.assertEqual(updated["capabilities"]["thinking_effort"], "xhigh")

                remove_local_model("local-test")
                restored = _decode_model(dict(row))
                self.assertEqual(restored["display_name"], "Database Name")
                self.assertEqual(restored["config_source"], "database")

    def test_corrupt_local_file_is_ignored_by_reads_but_blocks_writes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"FAB_LOCAL_MODELS_PATH": str(Path(temporary) / "models.json")}
        ):
            path = local_models_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{", encoding="utf-8")
            self.assertIsNone(get_local_model("broken"))
            with self.assertRaises(ValueError):
                save_local_model(
                    "broken",
                    display_name="Broken",
                    provider="openai-compatible",
                    provider_model="broken-v1",
                    base_url="http://127.0.0.1:8080/v1",
                    capabilities={},
                )

    def test_written_document_is_valid_and_versioned(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"FAB_LOCAL_MODELS_PATH": str(Path(temporary) / "models.json")}
        ):
            save_local_model(
                "local-test",
                display_name="Local Test",
                provider="openai-compatible",
                provider_model="local-test-v1",
                base_url="http://127.0.0.1:8080/v1",
                capabilities={},
            )
            document = json.loads(local_models_path().read_text(encoding="utf-8"))
            self.assertEqual(document["version"], 1)
            self.assertIn("local-test", document["models"])


if __name__ == "__main__":
    unittest.main()
