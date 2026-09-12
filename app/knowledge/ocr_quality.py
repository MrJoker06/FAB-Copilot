"""Deterministic OCR admission policy with confidence as a proxy signal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .ocr import OCRResult

POLICY_VERSION = "ocr-quality-v1"
MIN_CHARS = 3
MIN_MEAN_CONFIDENCE = 0.55
MAX_LOW_CONFIDENCE_RATIO = 0.65


@dataclass(frozen=True)
class OCRObservation:
    category: str
    result: OCRResult


@dataclass(frozen=True)
class QualityDecision:
    accepted: bool
    reason: str | None = None
    ocr_pages: int = 0
    recognized_pages: int = 0
    mean_confidence: float = 0.0
    low_confidence_ratio: float = 0.0


def evaluate_observations(observations: Iterable[OCRObservation]) -> QualityDecision:
    values = list(observations)
    recognized = [item.result for item in values if item.result.text.strip()]
    if any(
        item.result.has_visible_content and not item.result.text.strip()
        for item in values
    ):
        return QualityDecision(False, "visible_no_text", len(values), len(recognized))

    signal_values: list[float] = []
    low_confidence_mass = 0.0
    for result in recognized:
        if result.scores:
            signal_values.extend(result.scores)
            low_confidence_mass += sum(score < 0.60 for score in result.scores)
        else:
            signal_values.append(result.mean_confidence)
            low_confidence_mass += result.low_confidence_ratio

    aggregate = {
        "ocr_pages": len(values),
        "recognized_pages": len(recognized),
        "mean_confidence": (
            round(sum(signal_values) / len(signal_values), 4)
            if signal_values
            else 0.0
        ),
        "low_confidence_ratio": round(
            low_confidence_mass / len(signal_values),
            4,
        )
        if signal_values
        else 0.0,
    }

    if not recognized:
        reason = (
            "visible_no_text"
            if any(item.result.has_visible_content for item in values)
            else None
        )
        return QualityDecision(reason is None, reason, **aggregate)

    joined = "".join(item.text.strip() for item in recognized)
    if len(joined) < MIN_CHARS:
        return QualityDecision(False, "too_few_characters", **aggregate)
    if aggregate["mean_confidence"] < MIN_MEAN_CONFIDENCE:
        return QualityDecision(False, "mean_confidence_low", **aggregate)
    if aggregate["low_confidence_ratio"] > MAX_LOW_CONFIDENCE_RATIO:
        return QualityDecision(False, "low_confidence_ratio_high", **aggregate)
    return QualityDecision(True, **aggregate)
