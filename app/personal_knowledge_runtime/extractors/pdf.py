from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...knowledge.ocr import OCRFailedError, OCRUnavailableError
from ...knowledge.ocr_quality import OCRObservation
from ..contracts import ExtractedSection, PersonalKnowledgeError


def extract_pdf(
    path: Path,
    title: str,
    *,
    max_pdf_pages: int,
    max_rendered_pixels: int,
    min_native_pdf_text: int,
    extract_image_result: Callable,
) -> list[ExtractedSection]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "PDF 文件已经损坏，无法解析") from exc
    if reader.is_encrypted and not reader.decrypt(""):
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "PDF 已加密，无法解析")
    if len(reader.pages) > max_pdf_pages:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "PDF 页数超过安全限制")
    try:
        native = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "PDF 文件已经损坏，无法解析") from exc
    try:
        import pymupdf
    except ImportError as exc:
        raise PersonalKnowledgeError(503, "OCR_UNAVAILABLE", "离线 OCR 引擎不可用", True) from exc
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "PDF 文件已经损坏，无法解析") from exc

    sections: list[ExtractedSection] = []
    rendered_pixels = 0
    try:
        for index, text in enumerate(native, start=1):
            if len(text) >= min_native_pdf_text:
                sections.append(ExtractedSection(index, f"第 {index} 页", text))
                continue
            page = document.load_page(index - 1)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            rendered_pixels += pixmap.width * pixmap.height
            if rendered_pixels > max_rendered_pixels:
                raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "OCR 渲染内容超过安全限制")
            try:
                result = extract_image_result(pixmap.tobytes("png"))
            except OCRUnavailableError as exc:
                raise PersonalKnowledgeError(503, "OCR_UNAVAILABLE", "离线 OCR 引擎不可用", True) from exc
            except OCRFailedError as exc:
                raise PersonalKnowledgeError(422, "OCR_FAILED", "离线 OCR 识别失败", True) from exc
            combined = "\n".join(part for part in (native[index - 1], result.text) if part).strip()
            category = "mixed_pdf" if native[index - 1] else "scanned_pdf"
            sections.append(
                ExtractedSection(index, f"第 {index} 页", combined, OCRObservation(category, result))
            )
    finally:
        document.close()
    return sections
