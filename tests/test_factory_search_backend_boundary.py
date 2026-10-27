from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from app.core.identity import Principal
from app.knowledge import rag, search_registry
from app.knowledge.search_registry import (
    FactoryCatalogBackendError,
    FactorySearchBackendError,
    get_factory_catalog_backend,
    get_factory_search_backend,
    register_factory_search_backend,
)


class RecordingBackend:
    def __init__(self, aliases: dict | None = None, candidates: object | None = None):
        self.aliases = aliases if aliases is not None else {"Particles": ("颗粒",)}
        self.candidates = candidates if candidates is not None else [
            {
                "source_type": "knowledge",
                "reference_id": "KB-FAKE-1",
                "status": "Active",
                "title": "LITHO particle guide",
                "section": "Overview",
                "process_steps": "LITHO",
                "authority": 5,
                "tags": "Particles",
                "score": -1.0,
            }
        ]
        self.alias_principal = None
        self.search_principal = None
        self.request = None

    def defect_aliases(self, principal):
        self.alias_principal = principal
        return self.aliases

    def search(self, principal, request):
        self.search_principal = principal
        self.request = request
        return self.candidates


class RecordingCatalogBackend(RecordingBackend):
    def list_knowledge_documents(self, principal):
        self.catalog_principal = principal
        return [{"title": "Guide", "source": "guide.md", "status": "Active", "first_chunk_id": 9}]

    def get_knowledge_document(self, principal, chunk_id):
        self.catalog_principal = principal
        return {
            "selected_chunk_id": chunk_id,
            "document": {"chunk_id": chunk_id, "source": "guide.md", "status": "Active"},
            "chunks": [{"chunk_id": chunk_id, "source": "guide.md", "content": "Guide"}],
        }

    def list_historical_cases(self, principal):
        self.catalog_principal = principal
        return [{"case_id": "CASE-1", "case_status": "Validated"}]

    def get_historical_case(self, principal, case_id):
        self.catalog_principal = principal
        return {"case_id": case_id, "case_status": "Validated"}


class FactorySearchBackendBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.factories = search_registry._FACTORIES.copy()
        search_registry._FACTORIES.clear()

    def tearDown(self):
        search_registry._FACTORIES.clear()
        search_registry._FACTORIES.update(self.factories)

    def test_configured_provider_receives_tenant_roles_and_retrieval_request(self):
        backend = RecordingBackend()
        register_factory_search_backend("fake-search", lambda: backend)
        principal = Principal("tenant-a", "engineer-b", ("process", "reviewer"))
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "fake-search"}, clear=False), patch.object(
            rag, "current_principal", return_value=principal
        ):
            results = rag.search_knowledge("LITHO 颗粒", source_types=["knowledge"])
        self.assertEqual(results[0]["reference_id"], "KB-FAKE-1")
        self.assertIs(backend.alias_principal, principal)
        self.assertIs(backend.search_principal, principal)
        self.assertEqual(backend.request.inferred_filters["process_step"], "LITHO")
        self.assertEqual(backend.request.inferred_filters["defect_type"], "Particles")
        self.assertEqual(backend.request.candidate_limit, 30)
        self.assertEqual(backend.request.source_types, ("knowledge",))

    def test_unknown_or_broken_config_never_falls_back_to_sqlite(self):
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "missing"}, clear=False):
            with self.assertRaises(FactorySearchBackendError):
                get_factory_search_backend("missing")
        register_factory_search_backend("broken", lambda: object())
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "broken"}, clear=False):
            with self.assertRaises(FactorySearchBackendError):
                get_factory_search_backend("broken")

    def test_malformed_adapter_results_fail_closed(self):
        backend = RecordingBackend(candidates=[{"source_type": "knowledge", "reference_id": ""}])
        with patch.object(rag, "get_factory_search_backend", return_value=backend):
            with self.assertRaisesRegex(ValueError, "non-empty reference_id"):
                rag.search_knowledge("光刻")

    def test_empty_or_non_tokenizable_queries_do_not_resolve_a_backend(self):
        with patch.object(rag, "get_factory_search_backend", side_effect=AssertionError("must not resolve backend")):
            self.assertEqual(rag.search_knowledge(""), [])
            self.assertEqual(rag.search_knowledge("   \t"), [])
            self.assertEqual(rag.search_knowledge("？！"), [])

    def test_legacy_alias_patch_and_four_argument_filter_signature_remain_supported(self):
        with patch.object(rag, "get_active_defect_aliases", return_value={"Bridge": ("桥连",)}):
            filters = rag._infer_filters("发现桥连缺陷", None, None, None)
        self.assertEqual(filters["defect_type"], "Bridge")

    def test_catalog_uses_selected_backend_and_passes_principal(self):
        backend = RecordingCatalogBackend()
        register_factory_search_backend("fake-catalog", lambda: backend)
        principal = Principal("tenant-a", "engineer-b", ("process", "reviewer"))
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "fake-catalog"}, clear=False), patch.object(
            rag, "current_principal", return_value=principal
        ):
            self.assertEqual(rag.list_knowledge_documents()[0]["source"], "guide.md")
            self.assertEqual(rag.get_knowledge_document(9)["selected_chunk_id"], 9)
            self.assertEqual(rag.list_historical_cases()[0]["case_id"], "CASE-1")
            self.assertEqual(rag.get_historical_case("CASE-1")["case_status"], "Validated")
        self.assertIs(backend.catalog_principal, principal)

    def test_search_only_backend_cannot_fall_back_for_catalog(self):
        register_factory_search_backend("search-only", RecordingBackend)
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "search-only"}, clear=False):
            with self.assertRaises(FactoryCatalogBackendError):
                get_factory_catalog_backend("search-only")
            with self.assertRaises(FactoryCatalogBackendError):
                rag.list_knowledge_documents()

    def test_unknown_catalog_backend_is_not_a_missing_document_error(self):
        with patch.dict(os.environ, {"FAB_FACTORY_SEARCH_BACKEND": "missing"}, clear=False):
            with self.assertRaises(FactoryCatalogBackendError):
                rag.get_knowledge_document(1)

    def test_catalog_malformed_or_missing_responses_are_not_disguised_as_404(self):
        backend = RecordingCatalogBackend()
        backend.get_knowledge_document = lambda principal, chunk_id: {
            "selected_chunk_id": chunk_id + 1,
            "document": {"chunk_id": chunk_id, "source": "guide.md", "status": "Active"},
            "chunks": [{"chunk_id": chunk_id, "source": "guide.md"}],
        }
        with patch.object(rag, "get_factory_catalog_backend", return_value=backend):
            with self.assertRaisesRegex(RuntimeError, "selected_chunk_id"):
                rag.get_knowledge_document(1)
        backend.get_knowledge_document = lambda principal, chunk_id: None
        with patch.object(rag, "get_factory_catalog_backend", return_value=backend):
            with self.assertRaisesRegex(ValueError, "知识章节不存在"):
                rag.get_knowledge_document(1)


if __name__ == "__main__":
    unittest.main()
