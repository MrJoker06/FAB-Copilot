"""Model-facing views of lot commonality results stay small at the analysis limits."""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from app.core.lot_commonality_view import (
    CREATE_TOOL,
    MAX_MEMBERS,
    MAX_PASSES,
    MEMBERS_TOOL,
    RECORDS_TOOL,
    TOP_CANDIDATES,
    members_view,
    records_view,
    summary_view,
)
from app.core.tool_result_projection import project_result, prompt_content, truncation_details
from app.tools.lot_commonality.analysis import create_snapshot, read_members, read_records, summarize
from app.tools.lot_commonality.contracts import DEFAULT_LIMITS, LotHistory, LotHistoryBatch

# Measured ceiling for one prompt entry; a 40960-token slot also holds the
# system prompt, the tool catalog and the conversation history.
VIEW_BYTES = 8 * 1024
LOTS_PER_GROUP = 125
PASSES_PER_LOT = 100
MISSING_LOTS = 23


@dataclass(frozen=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("engineer",)


def _pass(lot: str, index: int, seq: int) -> dict:
    ref = f"pass:{lot}-{seq:03d}"
    equipment = f"ETCH-{(index + seq) % 40:02d}"
    chamber = f"CH-{'ABCD'[(index * 7 + seq) % 4]}"
    operation = f"L{seq % 10}/STEP{seq:03d}"
    return {
        "record_ref": ref, "source_record_refs": [ref], "source_pass_id": None, "lot_id": lot,
        "pass_seq": seq, "operation_key": operation, "layer": operation.split("/")[0],
        "step": operation.split("/")[1], "equipment_id": equipment, "chamber_granularity": "reported",
        "chamber_set_complete": True,
        "chambers": [{"chamber": chamber, "chamber_key": f"{equipment}/{chamber}", "wafer_count": None, "wafer_ids": None}],
        "allocated_wafer_total": None, "recipe": f"R{(index + seq) % 9}",
        "track_in_at": f"2026-11-10T{seq // 60:02d}:{seq % 60:02d}:00+08:00",
        "queue_hours": 0.1, "rework": {"is_rework": seq % 37 == 0, "rework_of_record_ref": None},
        "missing_fields": [],
    }


def _complete() -> dict:
    return {"records": "complete", "order": "complete", "truncated": False, "gaps": [], "failures": []}


class _Source:
    def __init__(self, lots: dict[str, LotHistory]) -> None:
        self.lots = lots

    def fetch(self, lot_ids, principal):
        return LotHistoryBatch(
            {"source_id": "capacity", "kind": "synthetic", "timezone": "Asia/Shanghai"},
            "2026-11-21T10:00:00+08:00",
            {lot: history for lot, history in self.lots.items() if lot in lot_ids},
        )


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class LotCommonalityViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        groups = []
        histories = {}
        for group_index in range(DEFAULT_LIMITS.max_groups):
            lots = [f"L2611{group_index}-{number:05d}" for number in range(LOTS_PER_GROUP)]
            groups.append({
                "group_id": f"g{group_index}", "name": f"第 {group_index + 1} 组",
                "role": "primary" if group_index == 0 else "normal_reference", "lot_ids": lots,
            })
            for index, lot in enumerate(lots):
                if index >= LOTS_PER_GROUP - MISSING_LOTS // DEFAULT_LIMITS.max_groups - 1:
                    continue
                passes = tuple(_pass(lot, index, seq) for seq in range(1, PASSES_PER_LOT + 1))
                histories[lot] = LotHistory(lot, 25, _complete(), passes)
        request = {
            "groups": groups, "dimensions": ["equipment", "chamber", "recipe", "path_adjacent"],
            "scope": {"time_range": None, "cutoff": None}, "timezone": "Asia/Shanghai",
        }
        cls.snapshot = create_snapshot(request, _Source(histories), _Principal())
        cls.ref = "lca_" + "a" * 32
        cls.summary = summarize(cls.snapshot, analysis_ref=cls.ref, created_at="t", expires_at=None)

    def test_summary_view_keeps_counts_and_states_its_omissions(self) -> None:
        candidates = self.summary["candidates"]
        self.assertGreater(len(candidates), TOP_CANDIDATES)
        view = summary_view(self.summary)
        self.assertLess(_size(view), VIEW_BYTES)
        self.assertGreater(_size(self.summary), 20 * VIEW_BYTES)
        self.assertEqual(view["analysis_ref"], self.ref)
        self.assertEqual(view["candidate_count"], len(candidates))
        self.assertEqual(view["omitted_candidates"], len(candidates) - TOP_CANDIDATES)
        self.assertEqual(
            [item["candidate_id"] for item in view["candidates"]],
            [item["candidate_id"] for item in candidates[:TOP_CANDIDATES]],
        )
        self.assertEqual(view["candidates"][0]["counts"], candidates[0]["counts"])
        for full, compact in zip(self.summary["groups"], view["groups"], strict=True):
            with self.subTest(group=full["group_id"]):
                self.assertEqual(sum(compact["lot_states"].values()), full["unique_count"])
                attention = [item for item in full["lot_states"] if item["state"] != "complete"]
                self.assertTrue(attention)
                self.assertEqual(
                    len(compact["lots_needing_attention"]) + compact["omitted_attention_lots"], len(attention)
                )

    def test_prompt_uses_the_compact_view_without_row_truncation_meta(self) -> None:
        self.assertEqual(project_result(CREATE_TOOL, self.summary), (summary_view(self.summary), None))
        payload = json.loads(prompt_content(CREATE_TOOL, self.summary))
        self.assertEqual(payload, {"ok": True, "data": summary_view(self.summary)})
        observation = type("Observation", (), {"status": "success", "tool": CREATE_TOOL, "result": self.summary})
        self.assertEqual(truncation_details([observation]), [])

    def test_member_and_record_pages_at_the_page_limit_stay_small(self) -> None:
        candidate = self.summary["candidates"][0]["candidate_id"]
        members, _next = read_members(
            self.snapshot,
            {"group_id": "g0", "conditions": [{"candidate_id": candidate}], "limit": DEFAULT_LIMITS.page_limit_max},
            analysis_ref=self.ref,
        )
        view = members_view(members)
        self.assertLess(_size(view), VIEW_BYTES)
        self.assertEqual(len(view["members"]), min(MAX_MEMBERS, len(members["members"])))
        self.assertEqual(view["omitted_members_on_page"], len(members["members"]) - len(view["members"]))
        self.assertEqual(view["counts"], members["counts"])
        self.assertEqual(project_result(MEMBERS_TOOL, members)[0], view)

        lots = self.snapshot.request["groups"][0]["lot_ids"][:5]
        records, _next = read_records(
            self.snapshot,
            {"group_id": "g0", "lot_ids": lots, "limit": DEFAULT_LIMITS.page_limit_max},
            analysis_ref=self.ref,
        )
        view = records_view(records)
        self.assertLess(_size(view), VIEW_BYTES)
        self.assertEqual(len(view["passes"]), MAX_PASSES)
        self.assertEqual(view["omitted_passes_on_page"], len(records["passes"]) - MAX_PASSES)
        self.assertEqual(view["page"], records["page"])
        self.assertEqual(project_result(RECORDS_TOOL, records)[0], view)


if __name__ == "__main__":
    unittest.main()
