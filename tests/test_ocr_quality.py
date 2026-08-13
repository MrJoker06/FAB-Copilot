from __future__ import annotations

import unittest

from app.ocr import OCRResult
from app.ocr_quality import OCRObservation, evaluate_observations


def result(
    text: str = "abc",
    mean: float = 0.9,
    low: float = 0.0,
    visible: bool = True,
) -> OCRResult:
    return OCRResult(text, (), len(text.splitlines()), mean, low, visible)


class OCRQualityTests(unittest.TestCase):
    def test_no_observations_are_accepted(self) -> None:
        self.assertTrue(evaluate_observations([]).accepted)

    def test_true_blank_page_is_accepted(self) -> None:
        decision = evaluate_observations(
            [OCRObservation("scanned_pdf", result("", visible=False))]
        )
        self.assertTrue(decision.accepted)
        self.assertIsNone(decision.reason)

    def test_visible_page_without_text_is_rejected(self) -> None:
        decision = evaluate_observations(
            [OCRObservation("image", result("", visible=True))]
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "visible_no_text")

    def test_visible_empty_page_rejects_mixed_document(self) -> None:
        recognized = OCRResult("recognized", (0.9,), 1, 0.9, 0.0, True)
        visible_empty = OCRResult("", (), 0, 0.0, 0.0, True)
        decision = evaluate_observations(
            [
                OCRObservation("mixed_pdf", recognized),
                OCRObservation("mixed_pdf", visible_empty),
            ]
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "visible_no_text")
        self.assertEqual(decision.recognized_pages, 1)

    def test_too_few_characters_reason(self) -> None:
        decision = evaluate_observations([OCRObservation("image", result("a"))])
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "too_few_characters")

    def test_mean_confidence_threshold_reason(self) -> None:
        decision = evaluate_observations(
            [OCRObservation("image", result("abc", mean=0.54))]
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "mean_confidence_low")

    def test_low_confidence_ratio_threshold_reason(self) -> None:
        decision = evaluate_observations(
            [OCRObservation("image", result("abc", low=0.66))]
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "low_confidence_ratio_high")

    def test_boundary_values_are_accepted(self) -> None:
        decision = evaluate_observations(
            [OCRObservation("image", result("abc", mean=0.55, low=0.65))]
        )
        self.assertTrue(decision.accepted)

    def test_score_aggregate_is_weighted_over_full_document(self) -> None:
        high = OCRResult("abc", (0.9, 0.9, 0.9), 1, 0.9, 0.0, True)
        low = OCRResult("def", (0.1,), 1, 0.1, 1.0, True)
        decision = evaluate_observations(
            [OCRObservation("x", high), OCRObservation("x", low)]
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.mean_confidence, 0.7)
        self.assertEqual(decision.low_confidence_ratio, 0.25)

    def test_scoreless_legacy_mock_falls_back_to_summary_statistics(self) -> None:
        first = result("abc", mean=0.8, low=0.0)
        second = result("def", mean=0.6, low=0.5)
        decision = evaluate_observations(
            [OCRObservation("x", first), OCRObservation("x", second)]
        )
        self.assertEqual(decision.mean_confidence, 0.7)
        self.assertEqual(decision.low_confidence_ratio, 0.25)

    def test_mixed_scored_and_scoreless_pages_include_both_signals(self) -> None:
        scored = OCRResult("abc", (0.9,), 1, 0.9, 0.0, True)
        first_legacy = result("def", mean=0.9, low=1.0)
        second_legacy = result("ghi", mean=0.9, low=1.0)
        decision = evaluate_observations(
            [
                OCRObservation("x", scored),
                OCRObservation("x", first_legacy),
                OCRObservation("x", second_legacy),
            ]
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.mean_confidence, 0.9)
        self.assertEqual(decision.low_confidence_ratio, 0.6667)
        self.assertEqual(decision.reason, "low_confidence_ratio_high")
