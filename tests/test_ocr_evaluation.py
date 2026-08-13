from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import evaluate_ocr


class OCREvaluationTests(unittest.TestCase):
    def test_metrics(self):
        self.assertEqual(evaluate_ocr.cer("abc", "abc"), 0)
        self.assertEqual(evaluate_ocr.cer("ab", "abc"), 1 / 3)
        self.assertEqual(evaluate_ocr.wer("a c", "a b c"), 1 / 3)
        self.assertEqual(evaluate_ocr.recall("A B", ["A", "C"]), .5)

    def test_schema_rejects_unknown_and_missing_category(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            path.write_text(json.dumps({"version": "x", "thresholds": {}, "cases": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_ocr.load_dataset(path)

    def test_real_dataset_writes_injected_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            report = evaluate_ocr.evaluate(report_path=report_path)
            self.assertTrue(report["passed"])
            self.assertTrue(report_path.is_file())
            self.assertEqual(
                list(report["categories"]),
                list(evaluate_ocr.CATEGORY_ORDER),
            )

    def test_tightened_threshold_fails_with_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            data = json.loads(evaluate_ocr.DATASET.read_text(encoding="utf-8"))
            data["thresholds"]["global"]["cer_max"] = 0.0
            path = Path(directory) / "gold.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            report = evaluate_ocr.evaluate(path, Path(directory) / "report.json")
            self.assertFalse(report["passed"])
            self.assertIn("cer > 0.0", report["details"][0]["failed_reasons"])

    def test_absolute_path_rejected(self):
        self._invalid_case("path", "/tmp/a.png")

    def test_traversal_rejected(self):
        self._invalid_case("path", "../a.png")

    def test_wrong_suffix_rejected(self):
        self._invalid_case("path", "chinese.pdf")

    def test_duplicate_id_rejected(self):
        data = self._data()
        data["cases"][1]["id"] = data["cases"][0]["id"]
        self._reject(data)
    def test_unknown_top_rejected(self):
        data = self._data()
        data["extra"] = True
        self._reject(data)
    def test_unknown_case_rejected(self):
        data = self._data()
        data["cases"][0]["extra"] = True
        self._reject(data)
    def test_missing_category_rejected(self):
        data = self._data()
        data["cases"] = data["cases"][1:]
        self._reject(data)
    def test_bad_threshold_values_rejected(self):
        for value in (True, float("nan"), float("inf"), 1.1):
            with self.subTest(value=value):
                data = self._data()
                data["thresholds"]["global"]["cer_max"] = value
                self._reject(data)
    def test_missing_category_fields_rejected(self):
        data = self._data()
        data["cases"][2].pop("fields")
        self._reject(data)

    def test_scanned_pdf_requires_only_fields(self):
        data = self._data()
        data["cases"][5]["cells"] = ["unexpected"]
        self._reject(data)

    def test_table_requires_only_cells(self):
        data = self._data()
        data["cases"][3]["fields"] = ["unexpected"]
        self._reject(data)

    def test_formula_requires_only_formula_tokens(self):
        data = self._data()
        data["cases"][4]["fields"] = ["unexpected"]
        self._reject(data)

    def test_bad_threshold_key_rejected(self):
        data = self._data()
        data["thresholds"]["global"]["unknown_max"] = 0.5
        self._reject(data)

    def test_missing_threshold_category_rejected(self):
        data = self._data()
        data["thresholds"]["categories"].pop("english")
        self._reject(data)

    def test_invalid_pages_rejected(self):
        for pages in ([0], [1, 1]):
            with self.subTest(pages=pages):
                data = self._data()
                data["cases"][0]["pages"] = pages
                self._reject(data)

    def test_missing_file_rejected(self):
        data = self._data()
        data["cases"][0]["path"] = "missing.png"
        self._reject(data)

    def test_sample_root_injection_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "samples"
            root.mkdir()
            for source in evaluate_ocr.ROOT.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            self.assertEqual(evaluate_ocr.load_dataset(sample_root=root)["version"], "ocr-gold-v2")

    def test_parent_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "samples"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "chinese.png").write_bytes((evaluate_ocr.ROOT / "chinese.png").read_bytes())
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlink unavailable")
            data = self._data()
            data["cases"][0]["path"] = "linked/chinese.png"
            with tempfile.TemporaryDirectory() as second:
                path = Path(second) / "gold.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    evaluate_ocr.load_dataset(path, root)

    def test_exact_case_keys_rejected(self):
        data = self._data()
        data["cases"][0]["fields"] = ["bad"]
        self._reject(data)

    def test_bool_page_rejected(self):
        data = self._data()
        data["cases"][0]["pages"] = [True]
        self._reject(data)

    def _data(self):
        return json.loads(evaluate_ocr.DATASET.read_text(encoding="utf-8"))

    def _reject(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gold.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_ocr.load_dataset(path)

    def _invalid_case(self, key, value):
        data = self._data()
        data["cases"][0][key] = value
        self._reject(data)
