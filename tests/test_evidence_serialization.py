from __future__ import annotations

import copy
import json
import unittest
from collections import namedtuple
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from unittest.mock import patch

from app.evidence.answer_synthesizer import AnswerContract, AnswerSynthesisReport
from app.evidence.serialization import json_dataclass_payload
from app.evidence.validator import EvidenceCheck, EvidenceValidation, ValidationIssue


def _oracle(value):
    return json.loads(json.dumps(asdict(value), ensure_ascii=False, default=str))


Point = namedtuple("Point", "x payload")


class Marker(Enum):
    READY = "ready"


class StringSubclass(str):
    pass


class IntegerSubclass(int):
    pass


class ListSubclass(list):
    pass


class TupleSubclass(tuple):
    pass


class DictSubclass(dict):
    pass


class CopyTracked:
    copies = 0

    def __deepcopy__(self, memo):
        type(self).copies += 1
        return type(self)()

    def __str__(self):
        return "copy-tracked"


class CopyFailure:
    def __deepcopy__(self, memo):
        raise RuntimeError("deepcopy failure")


@dataclass
class NestedPayload:
    payload: object


@dataclass
class MutablePayload:
    payload: dict[str, object]


class EvidenceSerializationTests(unittest.TestCase):
    def test_matches_stdlib_oracle_for_nested_and_json_edge_values(self):
        value = NestedPayload(
            {
                7: [None, True, 3, 1.25, "中文", ("tuple",)],
                "point": Point(
                    2, {"when": date(2026, 8, 7), "amount": Decimal("1.20")}
                ),
                "marker": Marker.READY,
                "subclasses": DictSubclass(
                    {"list": ListSubclass(["x"]), "tuple": TupleSubclass(("y",))}
                ),
            }
        )
        self.assertEqual(json_dataclass_payload(value), _oracle(value))

    def test_matches_stdlib_oracle_for_real_evidence_contracts(self):
        validation = EvidenceValidation(
            schema_version="1.2",
            validator_version="1.2.0",
            plan_id="plan-1",
            status="validated",
            coverage={"required_coverage_pct": 100.0},
            evidence_checks=(
                EvidenceCheck(
                    "e1", "证据", True, "covered", ("tool",), 1, 1, ("metric",), ()
                ),
            ),
            risks=(ValidationIssue("risk", "warning", ("e1",), "注意"),),
            conflicts=(),
            primary_scope_type="process",
            primary_scope_ids=("CMP",),
            primary_scope_labels=("CMP",),
            source_scope_roles={"TOOL:tool": "primary"},
            source_semantics={"TOOL:tool": {"nested": ["值"]}},
            observed_source_refs=("TOOL:tool",),
            allowed_conclusion_strength="supported",
            conclusion_guidance="guidance",
        )
        contract = AnswerContract(
            "1.2",
            "1.2.0",
            "plan-1",
            "required",
            "supported",
            False,
            ("结论",),
            ("TOOL:tool",),
            (),
            False,
            "process",
            ("CMP",),
            ("CMP",),
            {"TOOL:tool": "primary"},
            {"TOOL:tool": {"kind": "metric"}},
        )
        report = AnswerSynthesisReport(
            "1.2",
            "1.2.0",
            "plan-1",
            "structured",
            "supported",
            ("结论",),
            ("TOOL:tool",),
            (),
            0,
            (),
            ({"claim": "值"},),
            "2.0",
            ({"event": "ok"},),
        )
        for value in (validation, contract, report):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(value.to_dict(), _oracle(value))

    def test_result_is_independent_of_source_and_other_calls(self):
        value = MutablePayload({"nested": [{"value": 1}]})
        first = json_dataclass_payload(value)
        second = json_dataclass_payload(value)
        first["payload"]["nested"][0]["value"] = 99
        self.assertEqual(value.payload["nested"][0]["value"], 1)
        self.assertEqual(second["payload"]["nested"][0]["value"], 1)
        value.payload["nested"][0]["value"] = 42
        self.assertEqual(first["payload"]["nested"][0]["value"], 99)
        self.assertEqual(second["payload"]["nested"][0]["value"], 1)

    def test_exact_primitives_skip_deepcopy_but_subclasses_do_not(self):
        CopyTracked.copies = 0
        value = NestedPayload(
            [
                None,
                True,
                1,
                1.0,
                "plain",
                StringSubclass("sub"),
                IntegerSubclass(2),
                CopyTracked(),
            ]
        )
        expected = _oracle(value)
        with patch(
            "app.evidence.serialization.copy.deepcopy", wraps=copy.deepcopy
        ) as mocked:
            self.assertEqual(json_dataclass_payload(value), expected)
        copied_types = [type(call.args[0]) for call in mocked.call_args_list]
        self.assertNotIn(type(None), copied_types)
        self.assertNotIn(bool, copied_types)
        self.assertNotIn(int, copied_types)
        self.assertNotIn(float, copied_types)
        self.assertNotIn(str, copied_types)
        self.assertIn(StringSubclass, copied_types)
        self.assertIn(IntegerSubclass, copied_types)
        self.assertIn(CopyTracked, copied_types)
        self.assertGreaterEqual(CopyTracked.copies, 1)

    def test_illegal_roots_and_json_errors_match_stdlib_behavior(self):
        with self.assertRaisesRegex(TypeError, "dataclass instances"):
            json_dataclass_payload({"not": "a dataclass"})
        for illegal_root in (NestedPayload, object(), None):
            with self.subTest(illegal_root=illegal_root):
                with self.assertRaisesRegex(TypeError, "dataclass instances"):
                    json_dataclass_payload(illegal_root)
        unsupported_key = NestedPayload({object(): "value"})
        with self.assertRaises(TypeError):
            _oracle(unsupported_key)
        with self.assertRaises(TypeError):
            json_dataclass_payload(unsupported_key)
        failing_copy = NestedPayload(CopyFailure())
        with self.assertRaisesRegex(RuntimeError, "deepcopy failure"):
            _oracle(failing_copy)
        with self.assertRaisesRegex(RuntimeError, "deepcopy failure"):
            json_dataclass_payload(failing_copy)
