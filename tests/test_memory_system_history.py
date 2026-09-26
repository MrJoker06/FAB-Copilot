from __future__ import annotations

import unittest

from app.memory_system.context.builder import build_stage_memory_messages


class StageMemoryMessageTests(unittest.TestCase):
    def test_agent_loop_uses_exact_window_role_filter_and_truncation(self):
        history = [
            {"role": "user", "content": f"old-{index}"}
            for index in range(3)
        ] + [
            {"role": "system", "content": "skip"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "a" * 4001},
            {"role": "tool", "content": "skip"},
            {"role": "user", "content": 12},
            {"role": "assistant", "content": "last"},
        ]
        self.assertEqual(
            build_stage_memory_messages("agent_loop", history),
            [
                {"role": "user", "content": "old-1"},
                {"role": "user", "content": "old-2"},
                {"role": "assistant", "content": "a" * 4000},
                {"role": "user", "content": "12"},
                {"role": "assistant", "content": "last"},
            ],
        )

    def test_ready_synthesis_has_no_history_fragment(self):
        self.assertEqual(
            build_stage_memory_messages("ready_synthesis", [{"role": "user", "content": "x"}]),
            [],
        )

    def test_unknown_stage_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "未知的 memory stage"):
            build_stage_memory_messages("other", [])


if __name__ == "__main__":
    unittest.main()
