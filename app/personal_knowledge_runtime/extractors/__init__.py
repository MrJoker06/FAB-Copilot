from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..contracts import ExtractedSection, PersonalKnowledgeError
from .image import extract_image
from .office import extract_office
from .pdf import extract_pdf
from .text import extract_text


def extract_sections(
    path: Path,
    suffix: str,
    title: str,
    *,
    max_pdf_pages: int,
    max_image_pixels: int,
    max_rendered_pixels: int,
    min_native_pdf_text: int = 20,
    extract_image_result: Callable,
) -> list[ExtractedSection]:
    """Dispatch by supported suffix; dependencies are supplied by the facade."""
    if suffix in {".txt", ".md", ".csv"}:
        return extract_text(path, suffix, title)
    if suffix in {".docx", ".xlsx"}:
        return extract_office(path, suffix, title)
    if suffix == ".pdf":
        return extract_pdf(
            path,
            title,
            max_pdf_pages=max_pdf_pages,
            min_native_pdf_text=min_native_pdf_text,
            max_rendered_pixels=max_rendered_pixels,
            extract_image_result=extract_image_result,
        )
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return extract_image(
            path,
            max_image_pixels=max_image_pixels,
            max_rendered_pixels=max_rendered_pixels,
            extract_image_result=extract_image_result,
        )
    raise PersonalKnowledgeError(415, "UNSUPPORTED_FILE_TYPE", "当前不支持该文件类型")
