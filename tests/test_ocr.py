from __future__ import annotations

import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw
from app.knowledge.ocr import (
    OCRFailedError,
    OCRUnavailableError,
    extract_image_result,
    extract_image_text,
    reading_order_text,
)
from app.personal_knowledge_runtime.service import PersonalKnowledgeError, _extract_sections, _validate_file


class OfflineOCRTests(unittest.TestCase):
    def test_structured_result_statistics(self):
        output = SimpleNamespace(
            txts=("ok",),
            scores=(0.8,),
            boxes=(((1, 1), (20, 1), (20, 10), (1, 10)),),
        )
        result = extract_image_result(object(), engine=lambda _: output)
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.scores, (0.8,))
        self.assertEqual(result.line_count, 1)
        self.assertEqual(result.mean_confidence, 0.8)
        self.assertEqual(result.low_confidence_ratio, 0.0)

    def test_invalid_score_is_ocr_failed(self):
        for score in (float("nan"), 1.01):
            with self.subTest(score=score):
                output = SimpleNamespace(txts=("ok",), scores=(score,), boxes=())
                with self.assertRaises(OCRFailedError):
                    extract_image_text(object(), engine=lambda _: output)

    def test_white_and_visible_no_text_signal(self):
        blank = Image.new("RGB", (30, 30), "white")
        visible = Image.new("RGB", (30, 30), "black")
        output = SimpleNamespace(txts=(), scores=(), boxes=())
        self.assertFalse(extract_image_result(blank, engine=lambda _: output).has_visible_content)
        self.assertTrue(extract_image_result(visible, engine=lambda _: output).has_visible_content)
    def test_reading_order_keeps_columns_and_multilingual_formula_text(self):
        output = SimpleNamespace(txts=("B", "中文", "A", "E=mc²"), boxes=(((120, 120), (150, 120), (150, 140), (120, 140)), ((10, 10), (90, 10), (90, 30), (10, 30)), ((10, 120), (90, 120), (90, 140), (10, 140)), ((120, 10), (150, 10), (150, 30), (120, 30))))
        self.assertEqual(reading_order_text(output), "中文\tE=mc²\nA\tB")

    def test_adapter_maps_engine_failures(self):
        with self.assertRaises(OCRFailedError):
            extract_image_text(object(), engine=lambda _: (_ for _ in ()).throw(ValueError("bad")))
        with patch("app.knowledge.ocr.get_ocr_engine", side_effect=OCRUnavailableError("missing")):
            with self.assertRaises(OCRUnavailableError):
                extract_image_text(object())

    def test_shared_engine_inference_is_serialized(self):
        active = 0
        max_active = 0
        active_lock = threading.Lock()
        output = SimpleNamespace(txts=("ok",), boxes=(((1, 1), (20, 1), (20, 10), (1, 10)),))

        def engine(_):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with active_lock:
                active -= 1
            return output

        with patch("app.knowledge.ocr._engine", engine):
            threads = [threading.Thread(target=extract_image_text, args=(object(),)) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(max_active, 1)

    def test_image_validation_and_fake_ocr_page_number(self):
        image = Image.new("RGB", (60, 40), "white")
        payload = io.BytesIO()
        image.save(payload, "PNG")
        self.assertEqual(_validate_file("equipment.png", payload.getvalue())[1], "image/png")
        with self.assertRaises(PersonalKnowledgeError): _validate_file("equipment.png", b"not an image")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equipment.png"
            path.write_bytes(payload.getvalue())
            fake = SimpleNamespace(txts=("设备 EQ-01",), boxes=(((1, 1), (40, 1), (40, 20), (1, 20)),))
            with patch("app.personal_knowledge_runtime.service.extract_image_result", return_value=SimpleNamespace(text=reading_order_text(fake), scores=(0.99,), mean_confidence=0.99, low_confidence_ratio=0.0, has_visible_content=True)):
                sections = _extract_sections(path, ".png", "设备截图")
        self.assertEqual([(section.page_number, section.content) for section in sections], [(1, "设备 EQ-01")])

    def test_image_pixel_and_multiframe_tiff_limits(self):
        image = Image.new("RGB", (11, 10), "white")
        payload = io.BytesIO()
        image.save(payload, "PNG")
        with patch("app.personal_knowledge_runtime.service.MAX_OCR_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(PersonalKnowledgeError, "文件内容"):
                _validate_file("large.png", payload.getvalue())
        first = Image.new("RGB", (8, 8), "white")
        second = Image.new("RGB", (8, 8), "white")
        payload = io.BytesIO()
        first.save(payload, "TIFF", save_all=True, append_images=[second])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi.tiff"
            path.write_bytes(payload.getvalue())
            with patch("app.personal_knowledge_runtime.service.extract_image_result", side_effect=[SimpleNamespace(text="第一页", scores=(0.99,), mean_confidence=0.99, low_confidence_ratio=0.0, has_visible_content=True), SimpleNamespace(text="第二页", scores=(0.99,), mean_confidence=0.99, low_confidence_ratio=0.0, has_visible_content=True)]):
                sections = _extract_sections(path, ".tiff", "多页")
        self.assertEqual([section.page_number for section in sections], [1, 2])
        with patch("app.personal_knowledge_runtime.service.MAX_OCR_RENDERED_PIXELS", 100):
            with self.assertRaisesRegex(PersonalKnowledgeError, "文件内容"):
                _validate_file("multi.tiff", payload.getvalue())

    def test_pdf_page_limit_and_corrupt_signature_are_invalid_content(self):
        from pypdf import PdfWriter
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.add_blank_page(100, 100)
        writer.write(output)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-pages.pdf"
            path.write_bytes(output.getvalue())
            with patch("app.personal_knowledge_runtime.service.MAX_OCR_PDF_PAGES", 1):
                with self.assertRaisesRegex(PersonalKnowledgeError, "页数"):
                    _extract_sections(path, ".pdf", "页数")
            broken = Path(directory) / "broken.pdf"
            broken.write_bytes(b"%PDF-not-a-real-document")
            with self.assertRaises(PersonalKnowledgeError) as caught:
                _extract_sections(broken, ".pdf", "损坏")
        self.assertEqual(caught.exception.error_code, "INVALID_FILE_CONTENT")

    def test_image_ocr_error_mapping(self):
        image = Image.new("RGB", (20, 20), "white")
        payload = io.BytesIO()
        image.save(payload, "PNG")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equipment.png"
            path.write_bytes(payload.getvalue())
            for failure, code in ((OCRUnavailableError("missing"), "OCR_UNAVAILABLE"), (OCRFailedError("failed"), "OCR_FAILED")):
                with self.subTest(code=code), patch("app.personal_knowledge_runtime.service.extract_image_result", side_effect=failure):
                    with self.assertRaises(PersonalKnowledgeError) as caught:
                        _extract_sections(path, ".png", "设备")
                self.assertEqual(caught.exception.error_code, code)
                self.assertTrue(caught.exception.retryable)

    def test_mixed_pdf_preserves_native_text_and_ocrd_page_order(self):
        import pymupdf
        output = io.BytesIO()
        document = pymupdf.open()
        first = document.new_page()
        first.insert_text((20, 30), "Native text is long enough to preserve.")
        document.new_page()
        document.save(output)
        document.close()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.pdf"
            path.write_bytes(output.getvalue())
            replacement = SimpleNamespace(
                text="扫描第二页",
                scores=(0.99,),
                mean_confidence=0.99,
                low_confidence_ratio=0.0,
                has_visible_content=True,
            )
            with patch(
                "app.personal_knowledge_runtime.service.extract_image_result",
                return_value=replacement,
            ) as ocr:
                sections = _extract_sections(path, ".pdf", "混合")
        self.assertEqual([section.page_number for section in sections], [1, 2])
        self.assertIn("Native text", sections[0].content)
        self.assertEqual(sections[1].content, "扫描第二页")
        ocr.assert_called_once()

    def test_real_rapidocr_offline_smoke(self):
        image = Image.new("RGB", (500, 140), "white")
        font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
        if font_path.is_file():
            from PIL import ImageFont

            ImageDraw.Draw(image).text(
                (20, 30),
                "设备 EQ-01 检查 PASS",
                fill="black",
                font=ImageFont.truetype(font_path, size=32),
            )
            text = extract_image_text(image)
            self.assertIn("设备", text)
            self.assertRegex(text, r"(?i)(eq[- ]?01|pass)")
        else:
            ImageDraw.Draw(image).text((20, 30), "Equipment EQ-01 PASS", fill="black", font_size=28)
            self.assertRegex(extract_image_text(image), r"(?i)(equipment|eq.?01|pass)")
