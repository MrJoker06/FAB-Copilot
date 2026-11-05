from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.evidence.evidence_truncation import (
    TOOL_LIMITS,
    project_result,
    truncation_details,
    truncation_notices,
    truncation_prompt_note,
)


@dataclass(frozen=True)
class _Observation:
    tool: str
    result: object
    status: str = "success"


def _rows(count: int, **fields) -> list[dict]:
    return [dict({"id": index}, **fields) for index in range(count)]


class ProjectionTests(unittest.TestCase):
    def test_small_result_is_untouched(self):
        rows = _rows(5)
        projected, meta = project_result("get_sensor_summary", rows)
        self.assertIs(projected, rows)
        self.assertIsNone(meta)

    def test_unknown_tool_is_untouched(self):
        rows = _rows(500)
        projected, meta = project_result("get_fab_overview", rows)
        self.assertIs(projected, rows)
        self.assertIsNone(meta)

    def test_non_list_result_is_untouched(self):
        projected, meta = project_result("get_sensor_summary", {"rows": 1})
        self.assertEqual(projected, {"rows": 1})
        self.assertIsNone(meta)

    def test_sensor_summary_keeps_top_outliers(self):
        rows = [{"signal_name": f"s{index}", "flagged_outliers": index} for index in range(100)]
        projected, meta = project_result("get_sensor_summary", rows)
        self.assertEqual(len(projected), TOOL_LIMITS["get_sensor_summary"].rows)
        self.assertEqual(projected[0]["flagged_outliers"], 99)
        self.assertEqual(meta["total_rows"], 100)
        self.assertEqual(meta["shown_rows"], len(projected))
        self.assertIn("异常点", meta["sort"])

    def test_recent_excursions_are_sorted_by_time_desc(self):
        rows = [{"run_time": f"2026-01-{day:02d}T00:00:00"} for day in range(1, 31)]
        projected, meta = project_result("get_recent_excursions", rows)
        self.assertEqual(projected[0]["run_time"], "2026-01-30T00:00:00")
        self.assertEqual(len(projected), TOOL_LIMITS["get_recent_excursions"].rows)
        self.assertIsNotNone(meta)

    def test_equipment_health_prioritises_critical(self):
        rows = [{"equipment_id": f"E{index}", "health": "Healthy", "excursions": index} for index in range(20)]
        rows.append({"equipment_id": "CRIT", "health": "Critical", "excursions": 1})
        projected, _ = project_result("get_equipment_health", rows)
        self.assertEqual(projected[0]["equipment_id"], "CRIT")

    def test_knowledge_rows_drop_bulky_fields(self):
        rows = [
            {
                "reference_id": f"CASE-{index}",
                "title": "t",
                "excerpt": "e",
                "solution": "s",
                "tags": "x" * 500,
                "retrieval": {"lexical_rank": index},
            }
            for index in range(5)
        ]
        projected, meta = project_result("search_knowledge", rows)
        self.assertEqual(len(projected), TOOL_LIMITS["search_knowledge"].rows)
        self.assertNotIn("tags", projected[0])
        self.assertNotIn("retrieval", projected[0])
        self.assertIn("excerpt", projected[0])
        self.assertIsNotNone(meta)

    def test_prompt_note_reports_counts(self):
        note = truncation_prompt_note(
            "get_sensor_summary",
            {"shown_rows": 15, "total_rows": 100, "sort": "异常点从多到少"},
        )
        self.assertIn("15/100", note)
        self.assertIn("异常点从多到少", note)


class NoticeTests(unittest.TestCase):
    def test_no_notice_when_nothing_truncated(self):
        observations = [_Observation("get_sensor_summary", _rows(3))]
        self.assertEqual(truncation_notices(observations), [])
        self.assertEqual(truncation_details(observations), [])

    def test_notice_lists_every_truncated_tool(self):
        observations = [
            _Observation("get_sensor_summary", _rows(100)),
            _Observation("get_recent_excursions", _rows(50)),
            _Observation("get_fab_overview", _rows(1)),
        ]
        notices = truncation_notices(observations)
        self.assertEqual(len(notices), 1)
        self.assertIn("get_sensor_summary 15/100", notices[0])
        self.assertIn("get_recent_excursions 20/50", notices[0])
        self.assertNotIn("get_fab_overview", notices[0])

        details = truncation_details(observations)
        self.assertEqual({item["tool"] for item in details}, {"get_sensor_summary", "get_recent_excursions"})

    def test_failed_observations_are_ignored(self):
        observations = [_Observation("get_sensor_summary", _rows(100), status="error")]
        self.assertEqual(truncation_details(observations), [])


if __name__ == "__main__":
    unittest.main()
