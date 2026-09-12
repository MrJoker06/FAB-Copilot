"""Offline OCR adapter for personal knowledge ingestion.

RapidOCR packages its ONNX models in the installed wheel.  This module only
loads those local assets and intentionally has no model download fallback.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OCRUnavailableError(RuntimeError):
    pass


class OCRFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRResult:
    text: str
    scores: tuple[float, ...]
    line_count: int
    mean_confidence: float
    low_confidence_ratio: float
    has_visible_content: bool


_engine: Any | None = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()


def get_ocr_engine() -> Any:
    """Lazily construct one thread-safe shared RapidOCR engine."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            import rapidocr
            from rapidocr import RapidOCR

            model_dir = Path(rapidocr.__file__).resolve().parent / "models"
            required_models = (
                "PP-OCRv6_det_small.onnx",
                "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                "PP-OCRv6_rec_small.onnx",
            )
            if not all((model_dir / model).is_file() for model in required_models):
                raise OCRUnavailableError("离线 OCR 模型不可用")

            _engine = RapidOCR()
        except (ImportError, OSError, RuntimeError) as exc:
            raise OCRUnavailableError("离线 OCR 引擎不可用") from exc
    return _engine


def _box_position(box: Any) -> tuple[float, float, float]:
    points = list(box)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return min(ys), min(xs), max(ys) - min(ys)


def reading_order_text(output: Any) -> str:
    """Regroup detector boxes into visual rows, retaining table columns."""
    texts = list(getattr(output, "txts", ()) or ())
    raw_boxes = getattr(output, "boxes", ())
    boxes = list(raw_boxes) if raw_boxes is not None else []
    items = []
    for index, text in enumerate(texts):
        clean = str(text).strip()
        if not clean:
            continue
        if index < len(boxes):
            top, left, height = _box_position(boxes[index])
        else:
            top, left, height = float(index), 0.0, 1.0
        items.append((top, left, max(1.0, height), clean))
    items.sort(key=lambda item: (item[0], item[1]))
    rows: list[list[tuple[float, float, float, str]]] = []
    for item in items:
        if not rows:
            rows.append([item])
            continue
        row = rows[-1]
        baseline = sum(value[0] for value in row) / len(row)
        tolerance = max(8.0, max(value[2] for value in row + [item]) * 0.65)
        if abs(item[0] - baseline) <= tolerance:
            row.append(item)
        else:
            rows.append([item])
    return "\n".join(
        "\t".join(value[3] for value in sorted(row, key=lambda value: value[1]))
        for row in rows
    ).strip()


def extract_image_text(image: Any, engine: Callable[[Any], Any] | None = None) -> str:
    return extract_image_result(image, engine).text


def extract_image_result(image: Any, engine: Callable[[Any], Any] | None = None) -> OCRResult:
    try:
        if engine is not None:
            result = engine(image)
        else:
            # RapidOCR mutates per-call parameters, so the shared engine must
            # not serve concurrent calls. Injected fakes stay isolated in tests.
            with _inference_lock:
                result = get_ocr_engine()(image)
        raw_texts = list(getattr(result, "txts", ()) or ())
        raw_scores = list(getattr(result, "scores", ()) or ())
        scores = []
        for index, value in enumerate(raw_texts):
            if not str(value).strip():
                continue
            score = float(raw_scores[index]) if index < len(raw_scores) else 0.0
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise OCRFailedError("离线 OCR 返回无效置信信号")
            scores.append(score)
        text = reading_order_text(result)
        scores = tuple(scores)
        line_count = len([line for line in text.splitlines() if line.strip()])
        mean = sum(scores) / len(scores) if scores else 0.0
        low_ratio = sum(score < 0.60 for score in scores) / len(scores) if scores else 0.0
        # The caller supplies decoded image/PDF pixels. A non-white thumbnail is
        # a deliberately limited signal, not an attempt to infer document type.
        has_visible = bool(scores)
        if not has_visible:
            try:
                import io

                from PIL import Image, ImageStat

                if isinstance(image, bytes):
                    with Image.open(io.BytesIO(image)) as source:
                        grayscale = source.convert("L").resize((32, 32))
                        stats = ImageStat.Stat(grayscale)
                        has_visible = stats.var[0] > 2 or stats.mean[0] < 245
                else:
                    grayscale = image.convert("L").resize((32, 32))
                    stats = ImageStat.Stat(grayscale)
                    has_visible = stats.var[0] > 2 or stats.mean[0] < 245
            except Exception:
                has_visible = False
        return OCRResult(text, scores, line_count, mean, low_ratio, has_visible)
    except OCRUnavailableError:
        raise
    except Exception as exc:
        raise OCRFailedError("离线 OCR 识别失败") from exc
