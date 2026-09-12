from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from ...knowledge.ocr import OCRFailedError, OCRUnavailableError
from ...knowledge.ocr_quality import OCRObservation
from ..contracts import ExtractedSection, PersonalKnowledgeError


def extract_image(
    path: Path,
    *,
    max_image_pixels: int,
    max_rendered_pixels: int,
    extract_image_result: Callable,
) -> list[ExtractedSection]:
    try:
        with Image.open(path) as image:
            sections: list[ExtractedSection] = []
            rendered_pixels = 0
            frame_count = getattr(image, "n_frames", 1)
            for frame_index in range(frame_count):
                image.seek(frame_index)
                frame = ImageOps.exif_transpose(image).convert("RGB")
                pixels = frame.width * frame.height
                rendered_pixels += pixels
                if pixels > max_image_pixels or rendered_pixels > max_rendered_pixels:
                    raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "图片像素超过安全限制")
                result = extract_image_result(frame.copy())
                category = "multipage_tiff" if frame_count > 1 else "image"
                sections.append(
                    ExtractedSection(
                        frame_index + 1,
                        f"第 {frame_index + 1} 页",
                        result.text,
                        OCRObservation(category, result),
                    )
                )
    except OCRUnavailableError as exc:
        raise PersonalKnowledgeError(503, "OCR_UNAVAILABLE", "离线 OCR 引擎不可用", True) from exc
    except OCRFailedError as exc:
        raise PersonalKnowledgeError(422, "OCR_FAILED", "离线 OCR 识别失败", True) from exc
    return sections
