"""Independent boundary examples for the new business-evidence contract."""

from __future__ import annotations

import asyncio
import copy
import unittest
from dataclasses import replace
from types import SimpleNamespace

from app.bootstrap.evidence_assembly import validate_evidence as validate_diagnosis
from app.evidence.answer_synthesizer import create_answer_contract
from app.evidence.contracts import EvidencePolicy
from app.evidence.semantics import descriptor_for_tool
from app.evidence.validator import (
    EvidenceObservation,
    assess_validation,
    validate_evidence,
)
from app.skills.policies.manufacturing import EvidenceRequirement


def fixture(*, mode="each_row", fields=("a", "b")):
    step = SimpleNamespace(
        step_id="S01",
        tool="read_fixture",
        parameters={},
        evidence_ids=("CAP-01",),
        required=True,
        scope_role="primary",
        semantic_id="fixture",
        grain="record",
        filter_provenance="fixed_report",
        evidence_kind="record",
        evidence_scope={},
        evidence_start=None,
        evidence_end=None,
    )
    plan = SimpleNamespace(
        plan_id="fixture-plan",
        status="ready",
        steps=(step,),
        playbook_id="fixture-policy",
        scope_contract=SimpleNamespace(
            primary_scope_type="fab", primary_scope_ids=(), primary_scope_labels=()
        ),
    )
    requirement = EvidenceRequirement(
        "CAP-01", "fixture", "test", ("read_fixture",), fields, ()
    )
    policy = EvidencePolicy(
        "fixture-policy",
        "2.0.0",
        (requirement,),
        lambda expected, observed: (
            expected.tool == observed.tool and expected.parameters == observed.arguments
        ),
        lambda _items: [],
        lambda _items: [],
        descriptor_for_tool,
        (("CAP-01", mode),),
    )
    return plan, policy


class EvidencePolicyV2Tests(unittest.TestCase):
    def test_each_row_does_not_merge_incomplete_records_into_a_pass(self):
        plan, policy = fixture()
        observations = [
            EvidenceObservation("read_fixture", {}, "success", [{"a": 1}, {"b": 2}])
        ]
        each = assess_validation(plan, policy, observations)
        dataset = assess_validation(plan, replace(policy, row_modes=()), observations)
        self.assertEqual(each.evidence_checks[0].status, "partial")
        self.assertIs(each.evidence_sufficient, False)
        self.assertEqual(each.evidence_checks[0].missing_fields, ("a", "b"))
        self.assertIs(dataset.evidence_sufficient, True)

    def test_valid_report_is_checked_and_full_input_is_not_mutated(self):
        plan, policy = fixture()
        observations = [
            EvidenceObservation("read_fixture", {}, "success", [{"a": 1, "b": 2}])
        ]
        before = copy.deepcopy(observations)
        result = assess_validation(plan, policy, observations)
        self.assertEqual(result.assessment_status, "checked")
        self.assertIs(result.evidence_sufficient, True)
        self.assertEqual(
            result.policy_ref, {"component_id": "fixture-policy", "version": "2.0.0"}
        )
        self.assertEqual(observations, before)

    def test_empty_and_denied_results_do_not_prove_evidence(self):
        plan, policy = fixture()
        for status in ("success", "blocked", "error"):
            with self.subTest(status=status):
                result = assess_validation(
                    plan, policy, [EvidenceObservation("read_fixture", {}, status, [])]
                )
                self.assertEqual(result.assessment_status, "checked")
                self.assertIs(result.evidence_sufficient, False)
                self.assertEqual(result.coverage["required_covered"], 0)

    def test_no_optional_policy_is_not_a_pass(self):
        plan, _ = fixture()
        result = assess_validation(plan, None, [])
        self.assertEqual(result.assessment_status, "not_configured")
        self.assertIsNone(result.evidence_sufficient)
        self.assertFalse(result.enforced)

    def test_clarification_does_not_activate_a_diagnostic_policy(self):
        plan, policy = fixture()
        plan.status = "clarification_required"
        result = assess_validation(plan, policy, [])
        self.assertEqual(result.validator_version, "2.0.0")
        self.assertEqual(result.assessment_status, "checked")
        self.assertEqual(result.assessment_reason, "plan_not_ready")
        self.assertIsNone(result.evidence_sufficient)
        self.assertFalse(result.enforced)
        self.assertEqual(create_answer_contract(result).status, "not_applicable")

    def test_required_policy_cannot_disappear_from_a_ready_diagnosis(self):
        plan, _ = fixture()
        result = validate_diagnosis(plan, None, [])
        self.assertEqual(result.assessment_status, "check_failed")
        self.assertEqual(result.assessment_reason, "required_policy_missing")
        self.assertTrue(result.enforced)
        self.assertEqual(create_answer_contract(result).status, "required")

    def test_unknown_strength_wrong_version_and_unobserved_refs_fail_closed(self):
        plan, policy = fixture()
        raw = validate_evidence(plan, policy, [])
        invalid = (
            replace(raw, allowed_conclusion_strength="strong"),
            replace(raw, validator_version="9.0.0"),
            replace(raw, observed_source_refs=("TOOL:unexecuted",)),
            replace(raw, reference_evidence={"TOOL:unexecuted": {}}),
            replace(raw, coverage={**raw.coverage, "required_covered": 2}),
            replace(
                raw, coverage={**raw.coverage, "required_coverage_pct": float("nan")}
            ),
            replace(raw, causal_claims_allowed=True),
            replace(raw, evidence_sufficient=True),
            SimpleNamespace(
                status="validated", allowed_conclusion_strength="supported"
            ),
        )
        for item in invalid:
            with self.subTest(item=repr(item)[:80]):
                result = assess_validation(plan, policy, [], evaluate=lambda: item)
                self.assertEqual(result.assessment_status, "check_failed")
                self.assertEqual(result.assessment_reason, "invalid_checker_result")
                self.assertIsNone(result.evidence_sufficient)

    def test_zero_requirements_cannot_bypass_a_required_ready_check(self):
        plan, policy = fixture()
        result = assess_validation(plan, replace(policy, evidence_requirements=()), [])
        self.assertEqual(result.assessment_status, "check_failed")
        self.assertEqual(result.assessment_reason, "policy_not_applicable")
        self.assertIsNone(result.evidence_sufficient)

    def test_checker_exception_is_sanitized_and_cancellation_propagates(self):
        plan, policy = fixture()

        def fail():
            raise RuntimeError("secret internal connection")

        result = assess_validation(plan, policy, [], evaluate=fail)
        self.assertEqual(result.assessment_reason, "checker_unavailable")
        self.assertNotIn("secret", result.to_prompt())

        def cancel():
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            assess_validation(plan, policy, [], evaluate=cancel)

    def test_legacy_dataset_coverage_and_new_each_row_version_are_distinct(self):
        plan, policy = fixture()
        playbook = SimpleNamespace(
            playbook_id="PB-CAPABILITY-001",
            evidence_requirements=policy.evidence_requirements,
        )
        observations = [
            EvidenceObservation("read_fixture", {}, "success", [{"a": 1}, {"b": 2}])
        ]
        old = validate_diagnosis(plan, playbook, observations, policy_version="1.2.0")
        current = validate_diagnosis(plan, playbook, observations)
        self.assertIs(old.evidence_sufficient, True)
        self.assertIs(current.evidence_sufficient, False)
        self.assertEqual(old.validator_version, "1.2.0")
        self.assertEqual(current.validator_version, "2.0.0")

    def test_invalid_sample_and_missing_document_approval_are_not_certified(self):
        plan, policy = fixture(fields=("equipment_id", "samples"))
        playbook = SimpleNamespace(
            playbook_id="PB-CAPABILITY-001",
            evidence_requirements=policy.evidence_requirements,
        )
        for sample in (0, -1, True, "100", float("inf")):
            with self.subTest(sample=sample):
                report = validate_diagnosis(
                    plan,
                    playbook,
                    [
                        EvidenceObservation(
                            "read_fixture",
                            {},
                            "success",
                            [{"equipment_id": "E1", "samples": sample}],
                        )
                    ],
                )
                self.assertIs(report.evidence_sufficient, False)
                self.assertIn("invalid_sample", {issue.code for issue in report.risks})
        report = validate_diagnosis(
            plan,
            playbook,
            [
                EvidenceObservation(
                    "read_fixture",
                    {},
                    "success",
                    [
                        {
                            "equipment_id": "E1",
                            "samples": 100,
                            "source_type": "knowledge",
                        }
                    ],
                )
            ],
        )
        self.assertIs(report.evidence_sufficient, True)
        self.assertEqual(report.allowed_conclusion_strength, "supported_with_limits")
        self.assertIn(
            "document_status_unverified", {issue.code for issue in report.risks}
        )

    def test_disjoint_effective_windows_do_not_make_a_spec_conflict(self):
        plan, policy = fixture(fields=("equipment_id", "samples"))
        playbook = SimpleNamespace(
            playbook_id="PB-CAPABILITY-001",
            evidence_requirements=policy.evidence_requirements,
        )
        first = {
            "equipment_id": "E1",
            "metric_name": "m",
            "metric_unit": "nm",
            "samples": 100,
            "spec_lsl": 1,
            "effective_from": "2026-01-01",
            "effective_to": "2026-01-31",
        }
        second = {
            **first,
            "spec_lsl": 2,
            "effective_from": "2026-02-01",
            "effective_to": "2026-02-28",
        }
        separate = validate_diagnosis(
            plan,
            playbook,
            [EvidenceObservation("read_fixture", {}, "success", [first, second])],
        )
        self.assertEqual(separate.conflicts, ())
        self.assertIs(separate.evidence_sufficient, True)
        uncertain = {**second, "effective_from": None}
        conflict = validate_diagnosis(
            plan,
            playbook,
            [EvidenceObservation("read_fixture", {}, "success", [first, uncertain])],
        )
        self.assertIn("fact_conflict", {issue.code for issue in conflict.conflicts})
        self.assertIs(conflict.evidence_sufficient, False)
        # Equal numeric limits do not make differing units/versions comparable.
        for metadata in ({"metric_unit": "um"}, {"spec_version": "2"}):
            with self.subTest(metadata=metadata):
                original = {**first, "spec_version": "1"}
                result = validate_diagnosis(
                    plan,
                    playbook,
                    [
                        EvidenceObservation(
                            "read_fixture",
                            {},
                            "success",
                            [original, {**original, **metadata}],
                        )
                    ],
                )
                self.assertIn(
                    "comparability_unconfirmed",
                    {issue.code for issue in result.conflicts},
                )
                self.assertIs(result.evidence_sufficient, False)

    def test_different_document_versions_need_explicit_separate_effective_windows(self):
        plan, policy = fixture(fields=("reference_id", "source_type"))
        playbook = SimpleNamespace(
            playbook_id="PB-CAPABILITY-001",
            evidence_requirements=policy.evidence_requirements,
        )
        first = {
            "reference_id": "DOC",
            "source_type": "knowledge",
            "version": "1",
            "effective_from": "2026-01-01",
            "effective_to": "2026-01-31",
        }
        second = {
            **first,
            "version": "2",
            "effective_from": "2026-02-01",
            "effective_to": "2026-02-28",
        }
        result = validate_diagnosis(
            plan,
            playbook,
            [EvidenceObservation("read_fixture", {}, "success", [first, second])],
        )
        self.assertEqual(result.conflicts, ())
        self.assertIs(result.evidence_sufficient, True)
        result = validate_diagnosis(
            plan,
            playbook,
            [
                EvidenceObservation(
                    "read_fixture",
                    {},
                    "success",
                    [first, {**second, "effective_to": None}],
                )
            ],
        )
        self.assertIn(
            "comparability_unconfirmed", {item.code for item in result.conflicts}
        )
        self.assertIs(result.evidence_sufficient, False)


if __name__ == "__main__":
    unittest.main()
