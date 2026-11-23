"""B2 lot commonality aggregation against the frozen B1 samples and counterexamples."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.demo_data.schemas import MANUFACTURING_SCHEMA
from app.tools.lot_commonality.analysis import (
    AnalysisSnapshot,
    create_snapshot,
    read_members,
    read_records,
    summarize,
)
from app.tools.lot_commonality.contracts import (
    LotCommonalityAccessError,
    LotCommonalityDataError,
    LotCommonalityInputError,
    LotHistory,
    LotHistoryBatch,
)
from app.tools.lot_commonality.sqlite_source import SQLiteLotHistorySource

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lot_commonality"


@dataclass(frozen=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("engineer",)


PRINCIPAL = _Principal()
CHB = "ch:GATE/ETCH:ETCH-07/CH-B"
SAMPLE_CURSOR = "lcc_opaque_example_page_2"


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class FixtureSource:
    """Serves the hand-written B1 source facts; records every fetch."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.calls: list[tuple[str, ...]] = []

    def fetch(self, lot_ids, principal):
        self.calls.append(tuple(lot_ids))
        lots = {}
        for lot in self.document["lots"]:
            if lot["lot_id"] in lot_ids:
                passes = tuple(
                    item for item in self.document["passes"] if item["lot_id"] == lot["lot_id"]
                )
                lots[lot["lot_id"]] = LotHistory(lot["lot_id"], lot["wafer_count"], lot["coverage"], passes)
        return LotHistoryBatch(self.document["source"], "2026-11-21T10:00:00+08:00", lots)


def _cursor_offset(cursor):
    return {None: 0, SAMPLE_CURSOR: 4}[cursor]


def _with_cursor(body, next_offset):
    body["page"]["next_cursor"] = SAMPLE_CURSOR if next_offset == 4 else None
    return body


class FrozenSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_doc = _json("source_passes.json")
        cls.examples = _json("contract_examples.json")
        create = cls.examples["examples"]["create_analysis"]
        cls.expected = create["response"]
        cls.snapshot = create_snapshot(
            copy.deepcopy(create["request"]), FixtureSource(cls.source_doc), PRINCIPAL
        )

    def _summary(self, snapshot):
        return summarize(
            snapshot,
            analysis_ref=self.expected["analysis_ref"],
            created_at=self.expected["created_at"],
            expires_at=self.expected["expires_at"],
        )

    def test_create_matches_frozen_response(self) -> None:
        self.assertEqual(self._summary(self.snapshot), self.expected)

    def test_snapshot_round_trip_reads_the_same_version(self) -> None:
        restored = AnalysisSnapshot.from_dict(json.loads(json.dumps(self.snapshot.to_dict())))
        self.assertEqual(self._summary(restored), self.expected)

    def test_member_and_record_reads_match_frozen_responses(self) -> None:
        names = [
            "members_chamber_b",
            "members_chamber_b_rework_same_pass",
            "members_path_etch_metrology_page_1",
            "members_path_etch_metrology_page_2",
            "records_chamber_b",
        ]
        for name in names:
            with self.subTest(name):
                example = self.examples["examples"][name]
                query = {key: value for key, value in example["request"].items() if key != "cursor"}
                reader = read_records if name.startswith("records") else read_members
                body, next_offset = reader(
                    self.snapshot,
                    query,
                    analysis_ref=self.expected["analysis_ref"],
                    offset=_cursor_offset(example["request"]["cursor"]),
                )
                self.assertEqual(_with_cursor(body, next_offset), example["response"])

    def test_frozen_rejections(self) -> None:
        errors = self.examples["errors"]
        with self.assertRaises(LotCommonalityInputError) as caught:
            create_snapshot(copy.deepcopy(errors["cutoff_ambiguous"]["request"]), FixtureSource(self.source_doc), PRINCIPAL)
        self.assertEqual(caught.exception.error_code, "CUTOFF_AMBIGUOUS")
        self.assertEqual(caught.exception.detail, errors["cutoff_ambiguous"]["response"]["detail"])
        self.assertEqual(caught.exception.context, errors["cutoff_ambiguous"]["response"]["context"])

        query = {key: value for key, value in errors["same_pass_with_path"]["request"].items() if key != "cursor"}
        with self.assertRaises(LotCommonalityInputError) as caught:
            read_members(self.snapshot, query, analysis_ref="x")
        self.assertEqual(caught.exception.error_code, "VALIDATION_ERROR")
        self.assertEqual(caught.exception.detail, errors["same_pass_with_path"]["response"]["detail"])

        body = copy.deepcopy(self.examples["examples"]["create_analysis"]["request"])
        body["groups"][0]["lot_ids"] = [f"L{index:04d}" for index in range(201)]
        source = FixtureSource(self.source_doc)
        with self.assertRaises(LotCommonalityInputError) as caught:
            create_snapshot(body, source, PRINCIPAL)
        self.assertEqual(caught.exception.error_code, "ANALYSIS_LIMIT_EXCEEDED")
        self.assertEqual(caught.exception.context, errors["limit_exceeded"]["response"]["context"])
        self.assertEqual(source.calls, [], "limits are enforced before any source read")

    def test_operation_cutoff_drops_rework_after_the_cutoff(self) -> None:
        body = copy.deepcopy(self.examples["examples"]["create_analysis"]["request"])
        body["scope"]["cutoff"] = {"mode": "operation", "operation_key": "GATE/ETCH", "occurrence": 1, "per_lot": {}}
        snapshot = create_snapshot(body, FixtureSource(self.source_doc), PRINCIPAL)
        members, _ = read_members(
            snapshot,
            {"group_id": "main", "conditions": [{"candidate_id": CHB}, {"attribute": "rework", "value": True}], "match_scope": "same_pass", "status": "hit"},
            analysis_ref="x",
        )
        self.assertEqual(members["members"], [])
        records, _ = read_records(snapshot, {"group_id": "main", "lot_ids": ["E"]}, analysis_ref="x")
        self.assertEqual([item["record_ref"] for item in records["passes"]], ["pass:E-01", "pass:E-02"])

    def test_unknown_inputs_are_rejected_not_ignored(self) -> None:
        base = {"group_id": "main", "conditions": [{"candidate_id": CHB}], "match_scope": "any_pass"}
        for query in (
            {**base, "group_id": "nobody"},
            {**base, "conditions": [{"candidate_id": "ch:GATE/ETCH:ETCH-07/CH-Z"}]},
            {**base, "limit": 201},
            {**base, "extra": True},
        ):
            with self.subTest(query=query), self.assertRaises(LotCommonalityInputError):
                read_members(self.snapshot, query, analysis_ref="x")
        with self.assertRaises(LotCommonalityInputError):
            read_records(self.snapshot, {"group_id": "concurrent", "lot_ids": ["A"]}, analysis_ref="x")


def _pass(lot, seq, op, equipment, chamber, *, rework=False):
    ref = f"pass:{lot}-{seq:03d}"
    return {
        "record_ref": ref, "source_record_refs": [ref], "source_pass_id": None, "lot_id": lot,
        "pass_seq": seq, "operation_key": op, "layer": op.split("/")[0], "step": op.split("/")[1],
        "equipment_id": equipment, "chamber_granularity": "reported", "chamber_set_complete": True,
        "chambers": [{"chamber": chamber, "chamber_key": f"{equipment}/{chamber}", "wafer_count": None, "wafer_ids": None}],
        "allocated_wafer_total": None, "recipe": "R1", "track_in_at": f"2026-11-10T08:{seq % 60:02d}:00+08:00",
        "queue_hours": 0.1, "rework": {"is_rework": rework, "rework_of_record_ref": None}, "missing_fields": [],
    }


class StaticSource:
    def __init__(self, lots):
        self.lots = lots

    def fetch(self, lot_ids, principal):
        return LotHistoryBatch({"source_id": "test", "kind": "synthetic", "timezone": "Asia/Shanghai"}, "2026-11-21T10:00:00+08:00", {k: v for k, v in self.lots.items() if k in lot_ids})


def _request(lots, dimensions=("chamber",)):
    return {
        "groups": [{"group_id": "main", "name": "本次异常", "role": "primary", "lot_ids": list(lots)}],
        "dimensions": list(dimensions), "scope": {"time_range": None, "cutoff": None}, "timezone": "Asia/Shanghai",
    }


def _complete():
    return {"records": "complete", "order": "complete", "truncated": False, "gaps": [], "failures": []}


class CounterexampleTests(unittest.TestCase):
    def test_same_chamber_name_on_another_tool_is_a_separate_candidate(self) -> None:
        lots = {
            "P": LotHistory("P", 25, _complete(), (_pass("P", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
            "Q": LotHistory("Q", 25, _complete(), (_pass("Q", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
            "R": LotHistory("R", 25, _complete(), (_pass("R", 1, "GATE/ETCH", "ETCH-08", "CH-B"),)),
            "S": LotHistory("S", 25, _complete(), (_pass("S", 1, "GATE/ETCH", "ETCH-08", "CH-B"),)),
        }
        snapshot = create_snapshot(_request(lots), StaticSource(lots), PRINCIPAL)
        summary = summarize(snapshot, analysis_ref="x", created_at="t", expires_at="t")
        counts = {item["candidate_id"]: item["counts"]["main"] for item in summary["candidates"]}
        self.assertEqual(counts[CHB], {"hit": 2, "miss": 2, "unknown": 0, "denominator": 4})
        self.assertEqual(counts["ch:GATE/ETCH:ETCH-08/CH-B"]["hit"], 2)
        members, _ = read_members(snapshot, {"group_id": "main", "conditions": [{"candidate_id": CHB}]}, analysis_ref="x")
        self.assertEqual({m["lot_id"]: m["reasons"] for m in members["members"] if m["status"] == "miss"}, {"R": [{"code": "OTHER_VALUE"}], "S": [{"code": "OTHER_VALUE"}]})

    def test_incomplete_chamber_set_cannot_confirm_a_miss(self) -> None:
        partial = dict(_pass("R", 1, "GATE/ETCH", "ETCH-07", "CH-A"), chamber_set_complete=False)
        lots = {
            "P": LotHistory("P", 25, _complete(), (_pass("P", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
            "Q": LotHistory("Q", 25, _complete(), (_pass("Q", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
            "R": LotHistory("R", 25, _complete(), (partial,)),
            "S": LotHistory("S", 25, _complete(), (_pass("S", 1, "GATE/ETCH", "ETCH-07", "CH-A"),)),
        }
        snapshot = create_snapshot(_request(lots), StaticSource(lots), PRINCIPAL)
        members, _ = read_members(snapshot, {"group_id": "main", "conditions": [{"candidate_id": CHB}]}, analysis_ref="x")
        by_lot = {m["lot_id"]: (m["status"], m["reasons"]) for m in members["members"]}
        self.assertEqual(by_lot["R"], ("unknown", [{"code": "CHAMBER_SET_INCOMPLETE"}]))
        self.assertEqual(by_lot["S"], ("miss", [{"code": "OTHER_VALUE"}]))

    def test_not_found_lot_is_unknown_and_reported(self) -> None:
        lots = {
            "P": LotHistory("P", 25, _complete(), (_pass("P", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
            "Q": LotHistory("Q", 25, _complete(), (_pass("Q", 1, "GATE/ETCH", "ETCH-07", "CH-B"),)),
        }
        snapshot = create_snapshot(_request(["P", "Q", "GONE"]), StaticSource(lots), PRINCIPAL)
        summary = summarize(snapshot, analysis_ref="x", created_at="t", expires_at="t")
        self.assertIn({"lot_id": "GONE", "state": "not_found", "reasons": ["LOT_NOT_FOUND"]}, summary["groups"][0]["lot_states"])
        self.assertEqual(summary["candidates"][0]["counts"]["main"], {"hit": 2, "miss": 0, "unknown": 1, "denominator": 3})

    def test_malformed_source_records_are_a_source_failure(self) -> None:
        bad = dict(_pass("P", 1, "GATE/ETCH", "ETCH-07", "CH-B"))
        del bad["recipe"]
        lots = {"P": LotHistory("P", 25, _complete(), (bad,))}
        with self.assertRaises(LotCommonalityDataError):
            create_snapshot(_request(["P"]), StaticSource(lots), PRINCIPAL)


class _FailingPageSource(SQLiteLotHistorySource):
    fail_on_page = 2

    def _page(self, connection, chunk, after, size):
        self.pages = getattr(self, "pages", 0) + 1
        if self.pages == self.fail_on_page:
            raise sqlite3.OperationalError("injected")
        return super()._page(connection, chunk, after, size)


class SQLiteSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "manufacturing.db"
        connection = sqlite3.connect(self.path)
        connection.executescript(MANUFACTURING_SCHEMA)
        for lot in ("LA", "LB", "LC"):
            connection.execute(
                "INSERT INTO lots VALUES (?, 'P', 28, 'R', 'Normal', '2026-11-01T00:00:00', NULL, 'Running', 25, 20, 0.8, 1, 0)",
                (lot,),
            )
        start = datetime(2026, 11, 1, 8, 0)
        rows = []
        for lot, count in (("LA", 120), ("LB", 3), ("LC", 3)):
            for seq in range(1, count + 1):
                chamber = "B" if (lot == "LA" and seq == 101) or lot == "LB" else "A"
                rows.append((lot, "ETCH" if seq == 101 or lot != "LA" else "CLEAN", "ETCH-07" if seq == 101 or lot != "LA" else "CLEAN-01", chamber, "R1", (start + timedelta(minutes=seq)).isoformat(), 1, 1, 1, 0, "Defect density", "", 1, seq, "GATE" if seq == 101 or lot != "LA" else f"L{seq}", 0.5, int(lot == "LB" and seq == 2)))
        connection.executemany(
            "INSERT INTO process_runs(lot_id, process_step, equipment_id, chamber, recipe, run_time, temperature_c, pressure_torr, duration_sec, defect_density, measurement_name, measurement_unit, pass_flag, operation_seq, layer_name, queue_hours, rework_flag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()

    def _source(self, cls=SQLiteLotHistorySource, **overrides):
        options = {"demo_tenant_id": "demo", "timezone_name": "Asia/Shanghai", "utc_offset_minutes": 480, "page_size": 50, "clock": lambda: datetime(2026, 11, 21, 10, tzinfo=timezone(timedelta(hours=8)))}
        options.update(overrides)
        return cls(self.path, **options)

    def test_evidence_beyond_the_old_100_row_cap_is_found(self) -> None:
        batch = self._source().fetch(("LA", "LB", "LC", "NOPE"), PRINCIPAL)
        self.assertEqual(sorted(batch.lots), ["LA", "LB", "LC"])
        self.assertEqual(len(batch.lots["LA"].passes), 120)
        self.assertEqual(batch.lots["LA"].coverage["records"], "complete")
        snapshot = create_snapshot(_request(["LA", "LB", "LC", "NOPE"]), StaticSource(batch.lots), PRINCIPAL)
        members, _ = read_members(snapshot, {"group_id": "main", "conditions": [{"candidate_id": "ch:GATE/ETCH:ETCH-07/B"}]}, analysis_ref="x")
        hit = {m["lot_id"]: m["record_refs"] for m in members["members"] if m["status"] == "hit"}
        la_101 = next(item for item in batch.lots["LA"].passes if item["pass_seq"] == 101)
        self.assertEqual(hit, {"LA": [la_101["record_ref"]], "LB": [p["record_ref"] for p in batch.lots["LB"].passes]})
        self.assertEqual(la_101["track_in_at"], "2026-11-01T09:41:00+08:00")
        self.assertEqual(la_101["chamber_granularity"], "reported")
        self.assertTrue(batch.lots["LB"].passes[1]["rework"]["is_rework"])

    def test_row_budget_truncates_instead_of_inventing_misses(self) -> None:
        # 120 LA rows fit; the budget stops two rows into LB.
        batch = self._source(max_rows=122).fetch(("LA", "LB", "LC"), PRINCIPAL)
        self.assertEqual([len(batch.lots[lot].passes) for lot in ("LA", "LB", "LC")], [120, 2, 0])
        self.assertFalse(batch.lots["LA"].coverage["truncated"])
        for lot in ("LB", "LC"):
            self.assertTrue(batch.lots[lot].coverage["truncated"], lot)
        snapshot = create_snapshot(_request(["LA", "LB", "LC"], ("equipment",)), StaticSource(batch.lots), PRINCIPAL)
        summary = summarize(snapshot, analysis_ref="x", created_at="t", expires_at="t")
        self.assertEqual(summary["status"], "partial")
        counts = {item["candidate_id"]: item["counts"]["main"] for item in summary["candidates"]}
        self.assertEqual(counts["eq:GATE/ETCH:ETCH-07"], {"hit": 2, "miss": 0, "unknown": 1, "denominator": 3})
        members, _ = read_members(snapshot, {"group_id": "main", "conditions": [{"candidate_id": "eq:GATE/ETCH:ETCH-07"}]}, analysis_ref="x")
        self.assertEqual([(m["lot_id"], m["status"]) for m in members["members"]], [("LA", "hit"), ("LB", "hit"), ("LC", "unknown")])
        self.assertEqual(members["members"][2]["reasons"], [{"code": "SOURCE_TRUNCATED"}])

    def test_page_failure_midway_keeps_proven_hits_only(self) -> None:
        batch = self._source(_FailingPageSource).fetch(("LA", "LB", "LC"), PRINCIPAL)
        self.assertEqual(len(batch.lots["LA"].passes), 50)
        for lot in ("LA", "LB", "LC"):
            self.assertEqual(batch.lots[lot].coverage["failures"], [{"reason": "SOURCE_PAGE_FAILED"}], lot)
        snapshot = create_snapshot(_request(["LA", "LB", "LC"], ("equipment",)), StaticSource(batch.lots), PRINCIPAL)
        summary = summarize(snapshot, analysis_ref="x", created_at="t", expires_at="t")
        self.assertEqual(summary["status"], "partial")
        self.assertEqual([state["state"] for state in summary["groups"][0]["lot_states"]], ["incomplete"] * 3)

    def test_first_page_failure_is_a_whole_source_failure(self) -> None:
        source = self._source(_FailingPageSource)
        source.fail_on_page = 1
        with self.assertRaises(LotCommonalityDataError):
            source.fetch(("LA",), PRINCIPAL)
        with self.assertRaises(LotCommonalityDataError):
            SQLiteLotHistorySource(Path(self.directory.name) / "missing.db", demo_tenant_id="demo", timezone_name="Asia/Shanghai", utc_offset_minutes=480).fetch(("LA",), PRINCIPAL)

    def test_other_tenant_is_denied(self) -> None:
        with self.assertRaises(LotCommonalityAccessError):
            self._source().fetch(("LA",), _Principal(tenant_id="other"))


if __name__ == "__main__":
    unittest.main()
