from __future__ import annotations

import unittest

from app.evidence_semantics import (
    EvidenceDescriptor, EvidenceScope, ScopeRelation, descriptor_for_tool,
    scope_relation, supports_claim,
)
from app.processes import MANUFACTURING_STEPS


class EvidenceSemanticsTests(unittest.TestCase):
    def test_every_registered_process_isolated_from_each_other_process(self):
        for process in MANUFACTURING_STEPS:
            for other in MANUFACTURING_STEPS:
                if process == other:
                    continue
                self.assertEqual(
                    scope_relation(EvidenceScope(process_steps=(process,)), EvidenceScope(process_steps=(other,))),
                    ScopeRelation.DISJOINT,
                )

    def test_equipment_and_lot_evidence_cannot_represent_broader_process_or_product(self):
        process = MANUFACTURING_STEPS[0]
        self.assertEqual(
            scope_relation(EvidenceScope(process_steps=(process,), equipment_ids=(f"{process}-01",)), EvidenceScope(process_steps=(process,))),
            ScopeRelation.NARROWER,
        )
        self.assertEqual(
            scope_relation(EvidenceScope(products=("P1",), lot_ids=("L1",)), EvidenceScope(products=("P1",))),
            ScopeRelation.NARROWER,
        )

    def test_unknown_or_sample_evidence_fails_closed_for_population_claim(self):
        process = MANUFACTURING_STEPS[0]
        claim_scope = EvidenceScope(process_steps=(process,))
        unknown = descriptor_for_tool("TOOL:X", "query_manufacturing_data", {"sql": "SELECT * FROM lots"})
        sample = descriptor_for_tool("TOOL:Y", "query_enterprise_data", {"process_step": process})
        self.assertFalse(supports_claim(unknown, kind="metric", semantic_id="process_run_pass_rate", scope=claim_scope, grain="process"))
        self.assertFalse(supports_claim(sample, kind="metric", semantic_id="process_run_pass_rate", scope=claim_scope, grain="process"))

    def test_fixed_process_report_has_exact_scope_and_semantic(self):
        process = MANUFACTURING_STEPS[0]
        descriptor = descriptor_for_tool("TOOL:S01", "get_process_pass_rate", {
            "start": "2026-01-01", "end": "2026-01-07", "process_step": process,
        })
        self.assertTrue(supports_claim(
            descriptor, kind="metric", semantic_id="process_run_pass_rate",
            scope=EvidenceScope(process_steps=(process,)), grain="process", start="2026-01-01", end="2026-01-07",
        ))

    def test_grain_and_time_are_required_for_statistical_claims(self):
        process = MANUFACTURING_STEPS[0]
        descriptor = descriptor_for_tool("TOOL:S01", "get_process_pass_rate", {
            "start": "2026-01-01", "end": "2026-01-07", "process_step": process,
        })
        scope = EvidenceScope(process_steps=(process,))
        self.assertFalse(supports_claim(descriptor, kind="metric", semantic_id="process_run_pass_rate", scope=scope, grain="equipment"))
        self.assertFalse(supports_claim(descriptor, kind="metric", semantic_id="process_run_pass_rate", scope=scope, grain="process"))
        self.assertFalse(supports_claim(descriptor, kind="metric", semantic_id="process_run_pass_rate", scope=scope, grain="process", start="2026-01-02", end="2026-01-07"))
