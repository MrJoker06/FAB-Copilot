from __future__ import annotations

import unittest

from app.knowledge_decision import (
    assess_retrieval,
    knowledge_anchor_terms,
    required_scopes,
    rewrite_query,
    usable_result,
)
from app.personal_knowledge import _fts_query as personal_fts_query
from app.rag import _tokenize_query


def _source(reference_id: str, source_type: str, confidence: str = "medium") -> dict:
    return {
        "reference_id": reference_id,
        "source_type": source_type,
        "retrieval": {"confidence": confidence},
    }


class KnowledgeDecisionTests(unittest.TestCase):
    def test_domain_tokenization_preserves_lithography_entity_and_bilingual_aliases(self):
        query = "为我简单介绍一下光刻"

        retrieval_tokens = _tokenize_query(query)
        decision_anchors = knowledge_anchor_terms(query)

        self.assertIn("光刻", retrieval_tokens)
        self.assertIn("photolithography", retrieval_tokens)
        self.assertIn("光刻", decision_anchors)
        self.assertIn("photolithography", decision_anchors)

    def test_personal_fts_query_expands_chinese_process_entity(self):
        fts_query = personal_fts_query("为我简单介绍一下光刻")

        self.assertIn('"photolithography"', fts_query)
        self.assertIn('"lithography"', fts_query)

    def test_medium_personal_english_lithography_document_is_usable_for_chinese_query(self):
        result = {
            "reference_id": "PERSONAL-LITHO-1",
            "source_type": "personal",
            "title": "Micron_Intro_to_Photolithography",
            "section": "Page 5",
            "excerpt": "Photolithography transfers a reticle pattern to photoresist.",
            "process_steps": [],
            "retrieval": {
                "confidence": "medium",
                "filters": {"process_step": "LITHO"},
            },
        }

        self.assertTrue(usable_result("为我简单介绍一下光刻", result))

    def test_medium_personal_unrelated_document_remains_filtered(self):
        result = {
            "reference_id": "PERSONAL-CMP-1",
            "source_type": "personal",
            "title": "CMP Pad Maintenance",
            "section": "Conditioning",
            "excerpt": "Pad conditioning and slurry flow maintenance steps.",
            "process_steps": [],
            "retrieval": {
                "confidence": "medium",
                "filters": {"process_step": "LITHO"},
            },
        }

        self.assertFalse(usable_result("为我简单介绍一下光刻", result))

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
