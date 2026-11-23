"""Frozen lot-commonality B1 contract samples agree with the plan's hand-specified expectations."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lot_commonality"
CHB = "ch:GATE/ETCH:ETCH-07/CH-B"
PATH_ETCH_METROLOGY = "path:GATE/ETCH>GATE/METROLOGY"
STATUS_ORDER = {"hit": 0, "miss": 1, "unknown": 2}
DIMENSION_ORDER = {"equipment": 0, "chamber": 1, "recipe": 2, "path_adjacent": 3}


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class LotCommonalityContractFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _load("source_passes.json")
        cls.contract = _load("contract_examples.json")
        cls.passes = {item["record_ref"]: item for item in cls.source["passes"]}
        cls.lots = {item["lot_id"]: item for item in cls.source["lots"]}
        cls.analysis = cls.contract["examples"]["create_analysis"]["response"]
        cls.candidates = {item["candidate_id"]: item for item in cls.analysis["candidates"]}

    def _members(self, *names: str) -> list[dict]:
        return [
            member
            for name in names
            for member in self.contract["examples"][name]["response"]["members"]
        ]

    def test_plan_section_4_expectations(self) -> None:
        etch = self.candidates["eq:GATE/ETCH:ETCH-07"]["counts"]["main"]
        self.assertEqual((etch["hit"], etch["denominator"]), (8, 8))
        chb = self.candidates[CHB]["counts"]
        self.assertEqual(chb["main"], {"hit": 6, "miss": 1, "unknown": 1, "denominator": 8})
        self.assertEqual((chb["concurrent"]["hit"], chb["concurrent"]["denominator"]), (1, 3))
        self.assertEqual((chb["union"]["hit"], chb["union"]["denominator"]), (6, 10))
        self.assertEqual(self.analysis["union"]["unique_count"], 10)
        path = self.candidates[PATH_ETCH_METROLOGY]["counts"]["main"]
        self.assertEqual((path["hit"], path["miss"], path["unknown"]), (5, 2, 1))

        by_status: dict[str, list[str]] = {"hit": [], "miss": [], "unknown": []}
        for member in self._members("members_chamber_b"):
            by_status[member["status"]].append(member["lot_id"])
        self.assertEqual(by_status, {"hit": list("ABCDEF"), "miss": ["G"], "unknown": ["H"]})

        b_etch = self.passes["pass:B-02"]
        self.assertEqual(
            [(item["chamber"], item["wafer_count"]) for item in b_etch["chambers"]],
            [("CH-A", 12), ("CH-B", 13)],
        )
        self.assertEqual(b_etch["allocated_wafer_total"], 25)
        self.assertIsNone(self.passes["pass:C-02"]["allocated_wafer_total"])
        self.assertEqual(
            [ref for ref, item in self.passes.items() if item["lot_id"] == "E" and item["operation_key"] == "GATE/ETCH"],
            ["pass:E-02", "pass:E-03"],
        )
        rework_hits = [
            member["lot_id"]
            for member in self._members("members_chamber_b_rework_same_pass")
            if member["status"] == "hit"
        ]
        self.assertEqual(rework_hits, ["E"])
        path_misses = {
            member["lot_id"]: member["record_refs"]
            for member in self._members("members_path_etch_metrology_page_1", "members_path_etch_metrology_page_2")
            if member["status"] == "miss"
        }
        self.assertEqual(sorted(path_misses), ["F", "G"])
        for refs in path_misses.values():
            self.assertEqual(self.passes[refs[1]]["operation_key"], "GATE/WET-STRIP")

    def test_source_facts_are_internally_consistent(self) -> None:
        self.assertEqual(self.source["classification"], "synthetic_non_production")
        for ref, item in self.passes.items():
            self.assertIn(item["lot_id"], self.lots, ref)
            counts = [chamber["wafer_count"] for chamber in item["chambers"]]
            if item["chambers"] and None not in counts:
                self.assertEqual(item["allocated_wafer_total"], sum(counts), ref)
                self.assertLessEqual(sum(counts), self.lots[item["lot_id"]]["wafer_count"], ref)
            else:
                self.assertIsNone(item["allocated_wafer_total"], ref)
            for chamber in item["chambers"]:
                self.assertEqual(chamber["chamber_key"], f"{item['equipment_id']}/{chamber['chamber']}")
                if chamber["wafer_ids"] is not None:
                    self.assertEqual(len(chamber["wafer_ids"]), chamber["wafer_count"], ref)
            if item["chamber_granularity"] == "unknown":
                self.assertIn("chamber", item["missing_fields"], ref)
                self.assertFalse(item["chamber_set_complete"], ref)
            if item["pass_seq"] is None:
                self.assertIn("pass_seq", item["missing_fields"], ref)
            rework_of = item["rework"]["rework_of_record_ref"]
            if rework_of is not None:
                self.assertTrue(item["rework"]["is_rework"], ref)
                self.assertEqual(self.passes[rework_of]["lot_id"], item["lot_id"], ref)

    def test_candidate_counts_and_order(self) -> None:
        groups = {group["group_id"]: group for group in self.analysis["groups"]}
        denominators = {key: group["unique_count"] for key, group in groups.items()}
        denominators["union"] = self.analysis["union"]["unique_count"]
        for group in groups.values():
            self.assertEqual(len(group["lot_states"]), group["unique_count"])
            self.assertEqual(group["input_count"] - len(group["duplicates"]), group["unique_count"])
        for candidate in self.analysis["candidates"]:
            for group_id, counts in candidate["counts"].items():
                self.assertEqual(counts["hit"] + counts["miss"] + counts["unknown"], counts["denominator"])
                self.assertEqual(counts["denominator"], denominators[group_id], candidate["candidate_id"])
            main = candidate["counts"]["main"]
            self.assertGreaterEqual(main["hit"], 2)
            self.assertEqual(candidate["all_shared"], main["hit"] == main["denominator"])
        keys = [
            (
                -item["counts"]["main"]["hit"],
                item["counts"]["main"]["unknown"],
                DIMENSION_ORDER[item["dimension"]],
                item["candidate_id"],
            )
            for item in self.analysis["candidates"]
        ]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            self.contract["examples"]["read_analysis"]["response"], self.analysis
        )

    def test_member_pages_match_counts_and_evidence(self) -> None:
        pages = {
            "chamber_b": ("members_chamber_b",),
            "rework": ("members_chamber_b_rework_same_pass",),
            "path": ("members_path_etch_metrology_page_1", "members_path_etch_metrology_page_2"),
        }
        for label, names in pages.items():
            responses = [self.contract["examples"][name]["response"] for name in names]
            members = self._members(*names)
            counts = responses[0]["counts"]
            for response in responses:
                self.assertEqual(response["counts"], counts, label)
                self.assertEqual(response["page"]["returned"], len(response["members"]), label)
                self.assertEqual(response["page"]["total"], len(members), label)
            self.assertIsNone(responses[-1]["page"]["next_cursor"], label)
            for response in responses[:-1]:
                self.assertIsNotNone(response["page"]["next_cursor"], label)
            tally = Counter(member["status"] for member in members)
            self.assertEqual(
                (tally["hit"], tally["miss"], tally["unknown"]),
                (counts["hit"], counts["miss"], counts["unknown"]),
                label,
            )
            self.assertEqual(len({member["lot_id"] for member in members}), counts["denominator"], label)
            order = [(STATUS_ORDER[member["status"]], member["lot_id"]) for member in members]
            self.assertEqual(order, sorted(order), label)
            evidence_times = []
            for member in members:
                self.assertTrue(member["record_refs"], (label, member["lot_id"]))
                for ref in member["record_refs"]:
                    self.assertEqual(self.passes[ref]["lot_id"], member["lot_id"], (label, ref))
                    if member["status"] == "hit":
                        evidence_times.append(self.passes[ref]["track_in_at"])
                self.assertEqual(bool(member["reasons"]), member["status"] != "hit", (label, member["lot_id"]))
            time_range = responses[0]["hit_time_range"]
            self.assertEqual((time_range["first"], time_range["last"]), (min(evidence_times), max(evidence_times)), label)

        for member in self._members("members_chamber_b"):
            evidence = [self.passes[ref] for ref in member["record_refs"]]
            if member["status"] == "hit":
                self.assertTrue(
                    all(any(c["chamber_key"] == "ETCH-07/CH-B" for c in item["chambers"]) for item in evidence),
                    member["lot_id"],
                )
            elif member["status"] == "miss":
                self.assertTrue(all(item["chamber_set_complete"] for item in evidence))
                self.assertFalse(any(c["chamber_key"] == "ETCH-07/CH-B" for item in evidence for c in item["chambers"]))
            else:
                self.assertTrue(all("chamber" in item["missing_fields"] for item in evidence))

    def test_records_are_unaltered_source_projection(self) -> None:
        example = self.contract["examples"]["records_chamber_b"]
        response = example["response"]
        requested = example["request"]["lot_ids"]
        self.assertEqual([lot["lot_id"] for lot in response["lots"]], requested)
        for lot in response["lots"]:
            self.assertEqual(lot["coverage"], self.lots[lot["lot_id"]]["coverage"])
        for item in response["passes"]:
            self.assertEqual(item, self.passes[item["record_ref"]])
        expected_refs = sorted(
            (ref for ref, item in self.passes.items() if item["lot_id"] in requested),
            key=lambda ref: (
                requested.index(self.passes[ref]["lot_id"]),
                self.passes[ref]["pass_seq"] is None,
                self.passes[ref]["pass_seq"] or 0,
                ref,
            ),
        )
        self.assertEqual([item["record_ref"] for item in response["passes"]], expected_refs)
        self.assertEqual(response["page"]["total"], len(expected_refs))

    def test_error_examples_use_http_envelope(self) -> None:
        for name, example in self.contract["errors"].items():
            self.assertGreaterEqual(example["status"], 400, name)
            body = example["response"]
            self.assertLessEqual({"error_code", "detail", "request_id", "retryable"}, set(body), name)
            self.assertLessEqual(set(body), {"error_code", "detail", "request_id", "retryable", "context"}, name)
            self.assertFalse(body["retryable"], name)
        denied = json.dumps(self.contract["errors"]["scope_denied"]["response"], ensure_ascii=False)
        self.assertNotIn("Z-RESTRICTED", denied)


if __name__ == "__main__":
    unittest.main()
