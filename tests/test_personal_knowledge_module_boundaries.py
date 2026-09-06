from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import app.personal_knowledge as facade
from app.personal_knowledge_runtime import contracts, metadata, storage


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


if __name__ == "__main__":
    unittest.main()
