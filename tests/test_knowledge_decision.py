from __future__ import annotations

import unittest

from app.knowledge_decision import assess_retrieval, required_scopes, rewrite_query


def _source(reference_id: str, source_type: str, confidence: str = "medium") -> dict:
    return {
        "reference_id": reference_id,
        "source_type": source_type,
        "retrieval": {"confidence": confidence},
    }


class KnowledgeDecisionTests(unittest.TestCase):
    def test_rewrite_normalizes_gan_and_records_si_assumption(self):
        rewrite = rewrite_query("GAN器件和S器件的差别")

        self.assertTrue(rewrite.changed)
        self.assertEqual(rewrite.query, "GaN器件和Si器件的差别")
        self.assertEqual(rewrite.assumptions, ("暂按 S 器件指 Si（硅）器件理解",))

    def test_case_scope_is_only_added_for_case_like_questions(self):
        self.assertEqual(required_scopes("GaN 和 Si 的差别"), ("personal", "knowledge"))
        self.assertEqual(required_scopes("设备异常的历史案例"), ("personal", "knowledge", "case"))

    def test_one_medium_source_requires_hybrid_disclosure(self):
        rewrite = rewrite_query("什么是宽禁带半导体")
        source = _source("PERSONAL-1", "personal")
        decision = assess_retrieval(
            [{
                "scope": "personal", "status": "success", "raw_count": 1,
                "usable_count": 1, "reference_ids": ["PERSONAL-1"],
            }],
            [source],
            rewrite,
        )

        self.assertEqual(decision.state, "HYBRID_GENERAL_SUPPLEMENT")
        self.assertTrue(decision.model_knowledge_allowed)
        self.assertIn("部分相关内容", decision.disclosure or "")

    def test_personal_and_factory_evidence_produce_mixed_grounding(self):
        rewrite = rewrite_query("什么是宽禁带半导体")
        sources = [
            _source("PERSONAL-1", "personal", "high"),
            _source("KB-1", "knowledge", "medium"),
        ]
        decision = assess_retrieval(
            [
                {"scope": "personal", "status": "success"},
                {"scope": "knowledge", "status": "success"},
            ],
            sources,
            rewrite,
        )

        self.assertEqual(decision.state, "GROUND_MIXED")
        self.assertFalse(decision.model_knowledge_allowed)


if __name__ == "__main__":
    unittest.main()
