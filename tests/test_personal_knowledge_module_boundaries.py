from __future__ import annotations

import inspect
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import app.personal_knowledge as facade
from app.personal_knowledge_runtime import (
    contracts,
    documents,
    ingestion,
    metadata,
    search,
    storage,
)
from app.personal_knowledge_runtime.extractors import extract_sections
from app.personal_knowledge_runtime.extractors.pdf import extract_pdf


class PersonalKnowledgeModuleBoundaryTests(unittest.TestCase):
    def _png(self, size: tuple[int, int] = (11, 10)) -> bytes:
        output = io.BytesIO()
        Image.new("RGB", size, "white").save(output, "PNG")
        return output.getvalue()

    def test_facade_exports_runtime_contract_identities(self):
        self.assertIs(facade.PersonalKnowledgeError, contracts.PersonalKnowledgeError)
        self.assertIs(facade.PersonalDocumentMetadata, contracts.PersonalDocumentMetadata)
        self.assertIs(facade.PersonalDocumentPatch, contracts.PersonalDocumentPatch)
        self.assertIs(facade.ExtractedSection, contracts.ExtractedSection)
        self.assertEqual(
            facade.PersonalDocumentMetadata.model_json_schema(),
            contracts.PersonalDocumentMetadata.model_json_schema(),
        )

    def test_facade_file_limit_patch_is_forwarded_to_storage(self):
        with patch("app.personal_knowledge.MAX_OCR_IMAGE_PIXELS", 100):
            with self.assertRaises(facade.PersonalKnowledgeError) as caught:
                facade._validate_file("large.png", self._png())
        self.assertEqual(caught.exception.error_code, "INVALID_FILE_CONTENT")

    def test_facade_settings_patch_is_forwarded_to_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(personal_knowledge_storage_path=root)
            with patch("app.personal_knowledge.get_settings", return_value=settings):
                self.assertEqual(facade._storage_path("owner/source.txt"), root / "owner/source.txt")
                with self.assertRaises(facade.PersonalKnowledgeError) as caught:
                    facade._storage_path("../outside.txt")
        self.assertEqual(caught.exception.error_code, "STORAGE_PATH_ERROR")

    def test_metadata_runtime_keeps_acl_fields_hidden_and_tag_order(self):
        row = {
            "document_id": "document", "owner_user_id": "owner", "storage_key": "secret/path",
            "idempotency_key": "secret-key", "process_steps_json": '["ETCH"]',
            "equipment_ids_json": '["EQ-01"]', "tags_json": '["first", "second"]',
        }
        result = metadata._document_dict(row)
        self.assertEqual(result["tags"], ["first", "second"])
        self.assertEqual(result["tags_source"], "auto")
        self.assertFalse({"owner_user_id", "storage_key", "idempotency_key"} & result.keys())
        sections = [contracts.ExtractedSection(None, "body", "ETCH EQ-01 SOP scratch")]
        self.assertEqual(facade._automatic_tags("", "guide.pdf", sections), metadata._automatic_tags("", "guide.pdf", sections))

    def test_storage_owns_validation_and_facade_remains_thin_wrapper(self):
        self.assertEqual(storage._validate_file("document.txt", b"hello"), (".txt", "text/plain"))
        self.assertIs(facade.SUPPORTED_SUFFIXES, storage.SUPPORTED_SUFFIXES)
        self.assertNotIn("ZipFile", facade._validate_file.__code__.co_names)
        self.assertEqual(facade._safe_filename(r"folder\\ document.txt"), "document.txt")

    def test_runtime_extractors_dispatch_by_format_without_facade_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.txt"
            path.write_text("body", encoding="utf-8")
            sections = extract_sections(
                path, ".txt", "title", max_pdf_pages=1, max_image_pixels=1,
                max_rendered_pixels=1, extract_image_result=lambda value: None,
            )
        self.assertEqual(sections[0].content, "body")
        self.assertEqual(ingestion.split_content("a"), ["a"])
        self.assertNotIn("_text_sections", facade._extract_sections.__code__.co_names)
        self.assertNotIn("_extract_sections", ingestion.process_document.__code__.co_names)

    def test_facade_ocr_function_patch_reaches_runtime_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            path.write_bytes(self._png())
            result = SimpleNamespace(text="patched")
            with patch("app.personal_knowledge.extract_image_result", return_value=result):
                sections = facade._extract_sections(path, ".png", "image")
        self.assertEqual(sections[0].content, "patched")

    def test_facade_job_wrappers_resolve_patched_dependencies_at_call_time(self):
        row = {
            "job_id": "job", "document_id": "document", "status": "ready", "stage": "ready",
            "progress": 100, "attempt": 1, "error_code": None, "error_message": None,
            "retryable": 0, "created_at": "now", "updated_at": "now",
        }
        with patch.object(facade._jobs, "latest_job", return_value=row) as latest:
            self.assertIs(facade._latest_job("connection", "document", "owner"), row)
        latest.assert_called_once_with("connection", "document", "owner")
        self.assertNotIn("SELECT job_id", inspect.getsource(facade._latest_job))
        self.assertNotIn("DELETE FROM", inspect.getsource(facade.process_personal_document_deletion))

    def test_query_facade_is_sql_free_and_runtime_does_not_depend_on_facade(self):
        for function in (
            facade.list_personal_documents,
            facade.get_personal_document,
            facade.update_personal_document,
            facade.personal_document_file,
            facade.search_personal_knowledge,
            facade.get_personal_chunk,
        ):
            source = inspect.getsource(function)
            self.assertNotIn("SELECT ", source)
            self.assertNotIn("UPDATE ", source)
            self.assertNotIn("MATCH ", source)
        self.assertNotIn("personal_knowledge import", inspect.getsource(documents))
        self.assertNotIn("personal_knowledge import", inspect.getsource(search))

    def test_query_wrappers_resolve_patched_facade_globals_at_call_time(self):
        patched_session = object()
        with patch("app.personal_knowledge.db_session", patched_session), patch(
            "app.personal_knowledge._encode_cursor", return_value="encoded"
        ) as encode_cursor, patch(
            "app.personal_knowledge._decode_cursor", return_value=("time", "document")
        ) as decode_cursor, patch.object(
            facade._documents, "list_documents", return_value={"items": [], "next_cursor": None}
        ) as list_documents:
            self.assertEqual(facade.list_personal_documents("owner"), {"items": [], "next_cursor": None})
        document_deps = list_documents.call_args.args[0]
        self.assertIs(document_deps.db_session, patched_session)
        self.assertEqual(document_deps.encode_cursor("time", "document"), "encoded")
        self.assertEqual(document_deps.decode_cursor("cursor"), ("time", "document"))
        encode_cursor.assert_called_once_with("time", "document")
        decode_cursor.assert_called_once_with("cursor")

        with patch("app.personal_knowledge.get_personal_document", return_value={"document_id": "patched"}), patch.object(
            facade._documents, "update_document", return_value={"document_id": "patched"}
        ) as update_document:
            self.assertEqual(
                facade.update_personal_document("document", "owner", facade.PersonalDocumentPatch()),
                {"document_id": "patched"},
            )
        self.assertEqual(
            update_document.call_args.args[0].get_document("document", "owner"),
            {"document_id": "patched"},
        )

        with patch("app.personal_knowledge._fts_query", return_value='"patched"'), patch(
            "app.personal_knowledge._json_list", return_value=["patched-json"]
        ), patch.object(
            facade._search, "search_knowledge", return_value=[]
        ) as search_knowledge:
            self.assertEqual(facade.search_personal_knowledge("owner", "query"), [])
        search_deps = search_knowledge.call_args.args[0]
        self.assertEqual(search_deps.fts_query("anything"), '"patched"')
        self.assertEqual(search_deps.json_list("[]"), ["patched-json"])

        with patch("app.personal_knowledge.process_query_terms", return_value=["patched-term"]):
            self.assertIn('"patched-term"', facade._fts_query("ignored"))

    def test_facade_now_patch_reaches_job_update_without_a_database(self):
        executed: list[tuple[str, tuple]] = []

        class Connection:
            def execute(self, sql, parameters):
                executed.append((sql, parameters))

            def commit(self):
                pass

        class Session:
            def __enter__(self):
                return Connection()

            def __exit__(self, *unused):
                return False

        with patch("app.personal_knowledge.db_session", return_value=Session()), patch(
            "app.personal_knowledge._now", return_value="PATCHED-NOW"
        ):
            facade._update_progress("document", "owner", "job", "parsing", "extracting_text", 10)
        self.assertEqual(len(executed), 2)
        self.assertEqual(executed[0][1][1], "PATCHED-NOW")
        self.assertEqual(executed[1][1][3], "PATCHED-NOW")

    def test_pdf_pymupdf_open_error_has_legacy_invalid_content_mapping(self):
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readable-by-pypdf.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with path.open("wb") as handle:
                writer.write(handle)
            fake_pymupdf = SimpleNamespace(open=lambda unused: (_ for _ in ()).throw(RuntimeError("bad")))
            with patch.dict(sys.modules, {"pymupdf": fake_pymupdf}):
                with self.assertRaises(facade.PersonalKnowledgeError) as caught:
                    extract_pdf(
                        path,
                        "title",
                        max_pdf_pages=10,
                        max_rendered_pixels=1_000_000,
                        min_native_pdf_text=20,
                        extract_image_result=lambda value: None,
                    )
        self.assertEqual(caught.exception.error_code, "INVALID_FILE_CONTENT")
        self.assertEqual(caught.exception.detail, "PDF 文件已经损坏，无法解析")


if __name__ == "__main__":
    unittest.main()
