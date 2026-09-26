from __future__ import annotations

import subprocess
import sys
import unittest

from app.conversation import context_resolver as compatibility
from app.memory_system.contracts import ContextResolution
from app.memory_system.context.builder import context_system_message
from app.memory_system.context.history import build_contextualizer_messages
from app.memory_system.context.protocol import CONTEXTUALIZER_PROMPT
from app.memory_system.context.resolver import semantic_context_resolution


class MemorySystemContextTests(unittest.TestCase):
    def test_conversation_facade_reexports_the_same_implementation_objects(self):
        self.assertIs(compatibility.ContextResolution, ContextResolution)
        self.assertIs(compatibility.build_contextualizer_messages, build_contextualizer_messages)
        self.assertIs(compatibility.semantic_context_resolution, semantic_context_resolution)
        self.assertEqual(ContextResolution.__module__, "app.memory_system.contracts")
        self.assertEqual(semantic_context_resolution.__module__, "app.memory_system.context.resolver")

    def test_contextualizer_message_window_is_frozen(self):
        messages = build_contextualizer_messages(
            "  请继续解释   ",
            [
                {"message_id": 41, "role": "system", "content": "ignored"},
                {"message_id": 42, "role": "user", "content": " **前一个问题** "},
                {"message_id": 43, "role": "assistant", "content": "- 一\n- 二"},
            ],
        )
        self.assertEqual(messages, [
            {"role": "system", "content": CONTEXTUALIZER_PROMPT},
            {"role": "user", "content": "[message_id=42] 前一个问题"},
            {"role": "assistant", "content": "[message_id=43] - 一 - 二"},
            {"role": "user", "content": "请继续解释"},
        ])

    def test_contextualizer_window_preserves_plus_and_default_budgets(self):
        history = [
            {"message_id": index, "role": "assistant", "content": f"m{index}:" + ("x" * 2_000)}
            for index in range(1, 22)
        ]
        history[20] = {"message_id": 21, "role": "assistant", "content": "C++ / A+B"}
        messages = build_contextualizer_messages("q" * 5_000, history)

        historical = messages[1:-1]
        self.assertLessEqual(len(historical), 20)
        self.assertTrue(all(len(item["content"]) <= 1600 + len("[message_id=20] ") for item in historical))
        self.assertLessEqual(sum(len(item["content"]) for item in historical), 16_000)
        self.assertNotIn("[message_id=1]", "\n".join(item["content"] for item in historical))
        self.assertIn("C++ / A+B", historical[-1]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "q" * 4_000})

        per_role = build_contextualizer_messages(
            "question",
            [
                {"message_id": 1, "role": "user", "content": "u" * 1_001},
                {"message_id": 2, "role": "assistant", "content": "a" * 1_601},
            ],
        )
        self.assertEqual(len(per_role[1]["content"]), len("[message_id=1] ") + 1_000)
        self.assertEqual(len(per_role[2]["content"]), len("[message_id=2] ") + 1_600)

    def test_resolution_payload_and_context_system_message_are_frozen(self):
        resolution = semantic_context_resolution(
            "展开它",
            {
                "relation": "recall",
                "resolved_question": "展开此前设备异常的说明",
                "topic_anchor": "ignored when recall is rebuilt",
                "target_message_ids": [9],
                "confidence": 0.9,
                "intent_hint": "manufacturing_analysis",
            },
            [
                {"message_id": 8, "role": "user", "content": "说明设备异常"},
                {"message_id": 9, "role": "assistant", "content": "设备异常说明"},
            ],
        )
        self.assertEqual(resolution.to_dict(), {
            "original_question": "展开它",
            "resolved_question": "展开此前设备异常的说明",
            "applied": True,
            "strategy": "semantic_recall",
            "selected_context": "说明设备异常 | 设备异常说明",
            "relation": "recall",
            "confidence": 0.9,
            "source": "model",
            "intent_hint": "manufacturing_analysis",
            "target_message_ids": [9],
            "failure_reason": "",
            "resolution_state": "resolved",
            "turn_actions": [],
        })
        self.assertTrue(context_system_message(resolution).endswith('context_resolution={"original_question":"展开它","resolved_question":"展开此前设备异常的说明","applied":true,"strategy":"semantic_recall","selected_context":"说明设备异常 | 设备异常说明","relation":"recall","confidence":0.9,"source":"model","intent_hint":"manufacturing_analysis","target_message_ids":[9],"failure_reason":"","resolution_state":"resolved","turn_actions":[]}'))

    def test_pure_memory_import_has_no_network_or_database_side_effects(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import socket, sqlite3; "
                "socket.socket.connect=lambda *a, **k: (_ for _ in ()).throw(AssertionError('network during import')); "
                "sqlite3.connect=lambda *a, **k: (_ for _ in ()).throw(AssertionError('database during import')); "
                "import app.memory_system.contracts, app.memory_system.ports, app.memory_system.service, app.memory_system.context.protocol, app.memory_system.context.history, app.memory_system.context.resolver, app.memory_system.context.builder; "
                "print('import-ok')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "import-ok")


if __name__ == "__main__":
    unittest.main()
