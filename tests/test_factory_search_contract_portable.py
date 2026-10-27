from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.knowledge.search_contracts import (
    FactorySearchRequest,
    validate_factory_candidates,
    validate_historical_case,
    validate_historical_cases,
    validate_knowledge_document,
    validate_knowledge_documents,
)
from app.knowledge.search_query import search_terms


@dataclass(frozen=True)
class OfflinePrincipal:
    tenant_id: str = "tenant-a"
    user_id: str = "analyst-a"
    roles: tuple[str, ...] = ("analyst",)


class OfflineFactorySearchProvider:
    """A deliberately local fake: portable-contract tests open no I/O."""

    def defect_aliases(self, principal: OfflinePrincipal) -> dict[str, tuple[str, ...]]:
        self.principal = principal
        return {"Particles": ("particle", "颗粒")}

    def search(self, principal: OfflinePrincipal, request: FactorySearchRequest) -> list[dict]:
        self.principal = principal
        self.request = request
        return [{"source_type": "knowledge", "reference_id": "KB-OFFLINE-1", "status": "Active", "title": "Offline"}]

    def list_knowledge_documents(self, principal: OfflinePrincipal) -> list[dict]:
        self.catalog_principal = principal
        return [{"source": "offline.md", "status": "Active", "title": "Offline", "first_chunk_id": 7}]

    def get_knowledge_document(self, principal: OfflinePrincipal, chunk_id: int) -> dict:
        self.catalog_principal = principal
        return {
            "selected_chunk_id": chunk_id,
            "document": {"chunk_id": chunk_id, "source": "offline.md", "status": "Active"},
            "chunks": [{"chunk_id": chunk_id, "source": "offline.md", "content": "offline"}],
        }

    def list_historical_cases(self, principal: OfflinePrincipal) -> list[dict]:
        self.catalog_principal = principal
        return [{"case_id": "CASE-OFFLINE-1", "case_status": "Validated"}]

    def get_historical_case(self, principal: OfflinePrincipal, case_id: str) -> dict:
        self.catalog_principal = principal
        return {"case_id": case_id, "case_status": "Validated"}


class FactorySearchContractPortableTests(unittest.TestCase):
    def test_offline_provider_receives_structural_principal_and_request(self):
        provider = OfflineFactorySearchProvider()
        principal = OfflinePrincipal()
        request = FactorySearchRequest(
            raw_query="光刻颗粒",
            inferred_filters={"process_step": "LITHO", "equipment_id": None, "defect_type": "Particles"},
            candidate_limit=30,
        )
        self.assertEqual(provider.defect_aliases(principal)["Particles"], ("particle", "颗粒"))
        candidates = validate_factory_candidates(provider.search(principal, request))
        self.assertEqual(provider.principal.tenant_id, "tenant-a")
        self.assertEqual(candidates[0]["reference_id"], "KB-OFFLINE-1")
        self.assertIn("photolithography", search_terms("光刻颗粒"))

    def test_contract_rejects_malformed_candidates_and_invalid_source_scope(self):
        with self.assertRaisesRegex(ValueError, "non-empty reference_id"):
            validate_factory_candidates([{"source_type": "knowledge", "reference_id": ""}])
        with self.assertRaisesRegex(ValueError, "source_types"):
            FactorySearchRequest("query", {}, 30, ("personal",))

    def test_contract_rejects_inactive_knowledge_and_unvalidated_cases(self):
        with self.assertRaisesRegex(ValueError, "status Active"):
            validate_factory_candidates([{"source_type": "knowledge", "reference_id": "KB-DRAFT", "status": "Draft"}])
        with self.assertRaisesRegex(ValueError, "case_status Validated"):
            validate_factory_candidates([{"source_type": "case", "reference_id": "CASE-OPEN", "case_status": "Open"}])

    def test_offline_catalog_provider_receives_principal_and_validates_integrity(self):
        provider = OfflineFactorySearchProvider()
        principal = OfflinePrincipal()
        self.assertEqual(validate_knowledge_documents(provider.list_knowledge_documents(principal))[0]["source"], "offline.md")
        detail = validate_knowledge_document(7, provider.get_knowledge_document(principal, 7))
        self.assertEqual(detail["chunks"][0]["chunk_id"], 7)
        self.assertEqual(validate_historical_cases(provider.list_historical_cases(principal))[0]["case_id"], "CASE-OFFLINE-1")
        self.assertEqual(validate_historical_case("CASE-OFFLINE-1", provider.get_historical_case(principal, "CASE-OFFLINE-1"))["case_status"], "Validated")
        self.assertIs(provider.catalog_principal, principal)

    def test_catalog_contract_rejects_inactive_wrong_or_cross_source_responses(self):
        with self.assertRaisesRegex(RuntimeError, "status Active"):
            validate_knowledge_documents([{"source": "draft.md", "status": "Draft", "first_chunk_id": 1}])
        with self.assertRaisesRegex(RuntimeError, "first_chunk_id"):
            validate_knowledge_documents([{"source": "bad.md", "status": "Active", "first_chunk_id": True}])
        with self.assertRaisesRegex(RuntimeError, "selected_chunk_id"):
            validate_knowledge_document(3, {"selected_chunk_id": 4, "document": {}, "chunks": []})
        with self.assertRaisesRegex(RuntimeError, "match the document source"):
            validate_knowledge_document(3, {
                "selected_chunk_id": 3,
                "document": {"chunk_id": 3, "source": "one.md", "status": "Active"},
                "chunks": [{"chunk_id": 3, "source": "other.md", "content": "x"}],
            })
        with self.assertRaisesRegex(RuntimeError, "detail chunk_id"):
            validate_knowledge_document(3, {
                "selected_chunk_id": 3,
                "document": {"chunk_id": True, "source": "one.md", "status": "Active"},
                "chunks": [{"chunk_id": 3, "source": "one.md", "content": "x"}],
            })
        with self.assertRaisesRegex(RuntimeError, "string content"):
            validate_knowledge_document(3, {
                "selected_chunk_id": 3,
                "document": {"chunk_id": 3, "source": "one.md", "status": "Active"},
                "chunks": [{"chunk_id": 3, "source": "one.md", "content": None}],
            })
        with self.assertRaisesRegex(RuntimeError, "case_id does not match"):
            validate_historical_case("CASE-1", {"case_id": "CASE-2", "case_status": "Validated"})
        with self.assertRaisesRegex(RuntimeError, "case_status Validated"):
            validate_historical_cases([{"case_id": "CASE-1", "case_status": "Draft"}])


if __name__ == "__main__":
    unittest.main()
