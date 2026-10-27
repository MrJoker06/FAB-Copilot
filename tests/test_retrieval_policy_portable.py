from __future__ import annotations

import unittest

from app.knowledge.decision import (
    MODEL_ONLY_DISCLOSURE,
    QueryRewrite,
    assess_retrieval,
    usable_result,
)
from app.knowledge.ranking import _metadata_rerank


class RetrievalPolicyPortableTests(unittest.TestCase):
    def test_source_type_and_metadata_filters_exclude_non_matching_candidates(self):
        candidates = [
            {
                "source_type": "knowledge",
                "reference_id": "KB-LITHO",
                "process_steps": "LITHO",
                "authority": 5,
                "title": "Particle control",
                "tags": "particle",
            },
            {
                "source_type": "knowledge",
                "reference_id": "KB-ETCH",
                "process_steps": "ETCH",
                "authority": 5,
                "title": "Etch control",
            },
            {
                "source_type": "case",
                "reference_id": "CASE-VALID",
                "case_status": "Validated",
                "process_step": "LITHO",
                "equipment_family": "LITHO",
                "equipment_id": "LITHO-01",
                "defect_type": "Particle",
                "root_cause_confidence": 0.9,
                "occurred_date": "2020-01-01",
            },
            {
                "source_type": "case",
                "reference_id": "CASE-DRAFT",
                "case_status": "Draft",
                "process_step": "LITHO",
                "equipment_family": "LITHO",
                "equipment_id": "LITHO-01",
                "defect_type": "Particle",
                "root_cause_confidence": 1.0,
            },
            {"source_type": "personal", "reference_id": "PERSONAL"},
        ]
        selected = _metadata_rerank(
            candidates,
            {"process_step": "LITHO", "equipment_id": "LITHO-01", "defect_type": "Particle"},
            limit=5,
            source_types=["knowledge", "case"],
        )
        self.assertEqual({item["reference_id"] for item in selected}, {"KB-LITHO", "CASE-VALID"})

    def test_diverse_selection_prefers_the_best_representatives(self):
        candidates = [
            {"source_type": "knowledge", "reference_id": "KB-LOW", "process_steps": "ALL", "authority": 0},
            {"source_type": "personal", "reference_id": "PERSONAL", "process_steps": []},
            {
                "source_type": "case",
                "reference_id": "CASE-HIGH",
                "case_status": "Validated",
                "process_step": "LITHO",
                "equipment_family": "LITHO",
                "equipment_id": "LITHO-01",
                "defect_type": "Particle",
                "root_cause_confidence": 0.9,
                "occurred_date": "2020-01-01",
            },
        ]
        selected = _metadata_rerank(
            candidates,
            {"process_step": "LITHO", "equipment_id": "LITHO-01", "defect_type": "Particle"},
            limit=2,
            source_types=None,
        )
        self.assertEqual({item["reference_id"] for item in selected}, {"PERSONAL", "CASE-HIGH"})
        low_confidence = _metadata_rerank(
            [{"source_type": "knowledge", "reference_id": "KB-LOW", "process_steps": "ALL", "authority": 0}],
            {"process_step": None, "equipment_id": None, "defect_type": None},
            limit=1,
            source_types=["knowledge"],
        )
        self.assertEqual(low_confidence[0]["retrieval"]["confidence"], "low")

    def test_decision_fallback_and_grounded_answer_policy(self):
        fallback = assess_retrieval([], [], QueryRewrite("particle issue", False, ()))
        self.assertEqual(fallback.state, "MODEL_ONLY_FALLBACK")
        self.assertTrue(fallback.model_knowledge_allowed)
        self.assertEqual(fallback.disclosure, MODEL_ONLY_DISCLOSURE)

        grounded_source = {
            "reference_id": "KB-LITHO",
            "source_type": "knowledge",
            "title": "Particle control",
            "retrieval": {"confidence": "high"},
        }
        grounded = assess_retrieval(
            [{"scope": "knowledge", "status": "success"}],
            [grounded_source],
            QueryRewrite("particle issue", False, ()),
        )
        self.assertEqual(grounded.state, "GROUND_FACTORY")
        self.assertFalse(grounded.model_knowledge_allowed)
        self.assertIsNone(grounded.disclosure)
        self.assertFalse(usable_result("particle issue", {"retrieval": {"confidence": "low"}}))


if __name__ == "__main__":
    unittest.main()
