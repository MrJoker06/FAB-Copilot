from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .contracts import PersonalKnowledgeError


SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".md", ".txt", ".csv", ".xlsx", ".png", ".jpg",
    ".jpeg", ".tif", ".tiff",
}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}
MAX_OCR_PDF_PAGES = 100
MAX_OCR_IMAGE_PIXELS = 20_000_000
MAX_OCR_RENDERED_PIXELS = 80_000_000


def _safe_filename(filename: str | None) -> str:
    """Keep the basename only before a storage key is constructed."""
    cleaned = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not cleaned or len(cleaned) > 255:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "文件名为空或过长")
    return cleaned


def _validate_file(
    filename: str, data: bytes, *, max_ocr_pdf_pages: int = MAX_OCR_PDF_PAGES,
    max_ocr_image_pixels: int = MAX_OCR_IMAGE_PIXELS, max_ocr_rendered_pixels: int = MAX_OCR_RENDERED_PIXELS,
) -> tuple[str, str]:
    """Validate upload bytes against the declared suffix and OCR safety limits."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise PersonalKnowledgeError(415, "UNSUPPORTED_FILE_TYPE", "当前不支持该文件类型")
    if not data:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "文件内容为空")
    try:
        if suffix == ".pdf" and not data.startswith(b"%PDF-"):
            raise ValueError("invalid PDF signature")
        if suffix in {".docx", ".xlsx"}:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                expanded_size = sum(item.file_size for item in archive.infolist())
                compressed_size = max(1, sum(item.compress_size for item in archive.infolist()))
            expected = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
            if (
                expected not in names
                or expanded_size > 200 * 1024 * 1024
                or expanded_size / compressed_size > 100
            ):
                raise ValueError("invalid Office document signature")
        if suffix in {".md", ".txt", ".csv"}:
            if b"\x00" in data[:8192]:
                raise ValueError("binary content")
            data.decode("utf-8-sig")
        if suffix in IMAGE_FORMATS:
            from PIL import Image, UnidentifiedImageError
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    frame_count = getattr(image, "n_frames", 1)
                    if image.format != IMAGE_FORMATS[suffix] or frame_count > max_ocr_pdf_pages:
                        raise ValueError("invalid image content")
                    rendered_pixels = 0
                    for frame_index in range(frame_count):
                        image.seek(frame_index)
                        pixels = image.width * image.height
                        if pixels > max_ocr_image_pixels:
                            raise ValueError("invalid image content")
                        rendered_pixels += pixels
                    if rendered_pixels > max_ocr_rendered_pixels:
                        raise ValueError("invalid image content")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValueError("invalid image content") from exc
    except (UnicodeDecodeError, ValueError, zipfile.BadZipFile) as exc:
        raise PersonalKnowledgeError(422, "INVALID_FILE_CONTENT", "文件内容与声明类型不匹配或已经损坏") from exc
    return suffix, MIME_TYPES[suffix]


def _storage_path(storage_key: str, *, storage_root: Path) -> Path:
    """Resolve a storage key while rejecting traversal outside the configured root."""
    root = storage_root.resolve()
    target = (root / storage_key).resolve()
    if root != target and root not in target.parents:
        raise PersonalKnowledgeError(500, "STORAGE_PATH_ERROR", "文件存储路径不安全")
    return target
