"""The Skill evidence matcher is opt-in and rejects focus drift."""

from __future__ import annotations

import unittest
from dataclasses import replace

from app.bootstrap.litho_cpk_demo import run_litho_cpk_demo_sync
from app.evidence.skill_policy import validate_skill_evidence
from app.evidence.validator import validate_evidence


class SkillEvidencePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        result = run_litho_cpk_demo_sync()
        self.plan, self.playbook = result["plan"], result["playbook"]
        self.observations = result["observations"]

    def test_default_stays_12_and_skill_policy_covers_required_evidence(self) -> None:
        old = validate_evidence(self.plan, self.playbook, list(self.observations))
        new = validate_skill_evidence(self.plan, self.playbook, list(self.observations))
        self.assertEqual(old.validator_version, "1.2.0")
        self.assertEqual(
            next(x for x in old.evidence_checks if x.evidence_id == "CAP-04").status,
            "missing",
        )
        self.assertEqual(
            (new.validator_version, new.coverage["required_covered"]), ("1.3.0", 3)
        )

    def test_focus_drift_is_not_accepted(self) -> None:
        target = next(x for x in self.observations if x.tool == "search_knowledge")
        row = dict(target.result[0])
        retrieval = dict(row["retrieval"])
        filters = dict(retrieval["filters"])
        filters["process_step"] = "CMP"
        retrieval["filters"] = filters
        row["retrieval"] = retrieval
        changed = tuple(
            replace(x, result=[row]) if x is target else x for x in self.observations
        )
        result = validate_skill_evidence(self.plan, self.playbook, list(changed))
        self.assertEqual(
            next(x for x in result.evidence_checks if x.evidence_id == "CAP-04").status,
            "missing",
        )
        self.assertEqual(
            target.result[0]["retrieval"]["filters"]["process_step"], "LITHO"
        )

    def test_query_source_type_and_limit_drift_are_not_accepted(self) -> None:
        target = next(x for x in self.observations if x.tool == "search_knowledge")
        for key, value in (
            ("query", "wrong"),
            ("source_types", ["case"]),
            ("limit", 9),
        ):
            arguments = dict(target.arguments)
            arguments[key] = value
            changed = tuple(
                replace(x, arguments=arguments) if x is target else x
                for x in self.observations
            )
            result = validate_skill_evidence(self.plan, self.playbook, list(changed))
            check = next(x for x in result.evidence_checks if x.evidence_id == "CAP-04")
            self.assertEqual(check.status, "missing", key)

    def test_missing_or_conflicting_focus_metadata_is_not_accepted(self) -> None:
        target = next(x for x in self.observations if x.tool == "search_knowledge")
        row = dict(target.result[0])
        row["retrieval"] = {"filters": {}}
        missing = tuple(
            replace(x, result=[row]) if x is target else x for x in self.observations
        )
        missing_result = validate_skill_evidence(
            self.plan, self.playbook, list(missing)
        )
        self.assertEqual(
            next(
                x for x in missing_result.evidence_checks if x.evidence_id == "CAP-04"
            ).status,
            "missing",
        )
        arguments = dict(target.arguments)
        arguments["process_step"] = "CMP"
        conflict = tuple(
            replace(x, arguments=arguments) if x is target else x
            for x in self.observations
        )
        conflict_result = validate_skill_evidence(
            self.plan, self.playbook, list(conflict)
        )
        self.assertEqual(
            next(
                x for x in conflict_result.evidence_checks if x.evidence_id == "CAP-04"
            ).status,
            "missing",
        )

    def test_canonical_conflict_detection_remains_active(self) -> None:
        target = next(x for x in self.observations if x.tool == "get_recent_excursions")
        row = dict(target.result[0])
        row["spec_usl"] = 11.0
        changed = tuple(
            replace(x, result=[row]) if x is target else x for x in self.observations
        )
        result = validate_skill_evidence(self.plan, self.playbook, list(changed))
        self.assertTrue(any(item.code == "fact_conflict" for item in result.conflicts))
        self.assertEqual(result.allowed_conclusion_strength, "hypothesis_only")


if __name__ == "__main__":
    unittest.main()
