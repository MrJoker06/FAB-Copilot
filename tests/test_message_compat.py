from __future__ import annotations

import unittest

from app.model_gateway.message_compat import (
    chat_template_compat_enabled,
    flatten_system_messages,
)


class ChatTemplateCompatTests(unittest.TestCase):
    def test_disabled_by_default(self):
        for value in (None, "", "off", "0", "false"):
            self.assertFalse(chat_template_compat_enabled(value))

    def test_enabled_modes(self):
        for value in ("merge-system", "MERGE-SYSTEM", "qwen", "1", "true", "on"):
            self.assertTrue(chat_template_compat_enabled(value))

    def test_compliant_conversation_is_unchanged(self):
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        self.assertEqual(flatten_system_messages(messages), messages)

    def test_trailing_system_messages_move_to_the_front(self):
        messages = [
            {"role": "user", "content": "evidence"},
            {"role": "assistant", "content": "draft"},
            {"role": "system", "content": "validator"},
            {"role": "system", "content": "synthesizer"},
        ]
        flattened = flatten_system_messages(messages)
        self.assertEqual(flattened[0]["role"], "system")
        self.assertEqual(flattened[0]["content"], "validator\n\nsynthesizer")
        self.assertEqual(
            [item["content"] for item in flattened[1:]],
            ["evidence", "draft"],
        )

    def test_multiple_leading_system_messages_are_merged(self):
        messages = [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "q"},
        ]
        flattened = flatten_system_messages(messages)
        self.assertEqual(flattened, [
            {"role": "system", "content": "a\n\nb"},
            {"role": "user", "content": "q"},
        ])

    def test_conversation_without_system_messages_is_unchanged(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        self.assertEqual(flatten_system_messages(messages), messages)

    def test_blank_system_content_is_dropped(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "system", "content": "   "},
        ]
        self.assertEqual(flatten_system_messages(messages), [
            {"role": "user", "content": "q"},
        ])


if __name__ == "__main__":
    unittest.main()
