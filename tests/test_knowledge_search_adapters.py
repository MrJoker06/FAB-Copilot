"""Bounded source-adapter checks for the native knowledge search tool."""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolSource,
    ToolSourceKind,
)
from app.tools.knowledge_search.backend_search import BackendKnowledgeSearchAdapter
from app.demo_data.tool_sources.knowledge_search import FakeKnowledgeSearchAdapter
from app.knowledge import rag
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchInput,
    KnowledgeSearchQuery,
    KnowledgeSearchSnapshot,
    KnowledgeSearchTimeoutError,
    PersonalSearchBatch,
    knowledge_scope,
)
from app.tools.knowledge_search.handler import (
    KnowledgeSearchDependencies,
    knowledge_search_handler,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo-tenant"
    user_id: str = "demo-user"
    roles: tuple[str, ...] = ("analyst",)

    @property
    def knowledge_owner_id(self) -> str:
        return (
            self.user_id
            if self.tenant_id == "demo-tenant"
            else f"{self.tenant_id}:{self.user_id}"
        )


class RecordingFactory:
    def __init__(self) -> None:
        self.alias_calls: list[Principal] = []
        self.search_calls: list[tuple[Principal, object]] = []
        self.aliases: object = {"Particles": ("颗粒",)}
        self.rows: object = [
            {
                "source_type": "knowledge",
                "reference_id": "KB-1",
                "status": "Active",
                "title": "Particle control",
                "section": "Guide",
                "process_steps": "LITHO",
                "authority": 5,
                "tags": "particles",
            }
        ]

    def defect_aliases(self, principal: Principal) -> object:
        self.alias_calls.append(principal)
        return deepcopy(self.aliases)

    def search(self, principal: Principal, request: object) -> object:
        self.search_calls.append((principal, request))
        return deepcopy(self.rows)


class RecordingPersonal:
    def __init__(self) -> None:
        self.calls: list[tuple[Principal, str, str, int]] = []
        self.batch: object = PersonalSearchBatch(
            "demo-user",
            (
                {
                    "source_type": "personal",
                    "reference_id": "PERSONAL-1",
                    "title": "Private notes",
                    "process_steps": ["LITHO"],
                    "equipment_ids": [],
                    "tags": ["particles"],
                },
            ),
        )

    def search(
        self, principal: Principal, owner_user_id: str, query: str, limit: int
    ) -> object:
        self.calls.append((principal, owner_user_id, query, limit))
        return deepcopy(self.batch)


class ConformanceFactory(RecordingFactory):
    """Fixture source whose rows match the legacy backend's requested sources."""

    def __init__(self) -> None:
        super().__init__()
        self.rows = [
            {
                "source_type": "knowledge",
                "reference_id": "KB-LITHO",
                "status": "Active",
                "title": "LITHO particle control",
                "section": "Particle guide",
                "process_steps": "LITHO",
                "authority": 5,
                "tags": "Particles litho",
            },
            {
                "source_type": "knowledge",
                "reference_id": "KB-ALL",
                "status": "Active",
                "title": "General guide",
                "section": "Overview",
                "process_steps": "ALL",
                "authority": 1,
                "tags": "general",
            },
            {
                "source_type": "case",
                "reference_id": "CASE-EXACT",
                "case_status": "Validated",
                "title": "LITHO-01 particles",
                "section": "Historical case",
                "process_step": "LITHO",
                "equipment_id": "LITHO-01",
                "equipment_family": "LITHO",
                "defect_type": "Particles",
                "root_cause_confidence": 0.9,
                "occurred_date": "2020-01-01",
            },
            {
                "source_type": "case",
                "reference_id": "CASE-FAMILY",
                "case_status": "Validated",
                "title": "LITHO family particles",
                "section": "Historical case",
                "process_step": "LITHO",
                "equipment_id": "LITHO-02",
                "equipment_family": "LITHO",
                "defect_type": "Particles",
                "root_cause_confidence": 0.7,
                "occurred_date": "2020-01-01",
            },
        ]

    def search(self, principal: Principal, request: object) -> object:
        self.search_calls.append((principal, request))
        return [
            deepcopy(row)
            for row in self.rows
            if row["source_type"] in request.source_types
        ]


class ConformancePersonal:
    def __init__(self) -> None:
        self.calls: list[tuple[Principal, str, str, int]] = []

    def search(
        self, principal: Principal, owner_user_id: str, query: str, limit: int
    ) -> PersonalSearchBatch:
        self.calls.append((principal, owner_user_id, query, limit))
        return PersonalSearchBatch(
            owner_user_id,
            (
                {
                    "source_type": "personal",
                    "reference_id": "PERSONAL-LITHO",
                    "title": "Private LITHO notes",
                    "process_steps": ["LITHO"],
                    "equipment_ids": ["LITHO-01"],
                    "tags": ["Particles"],
                },
            ),
        )


class KnowledgeSearchAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = Principal()
        self.other_tenant = Principal("other-tenant", "demo-user")
        self.factory = RecordingFactory()
        self.personal = RecordingPersonal()

    def adapter(
        self, personal: RecordingPersonal | None = None
    ) -> BackendKnowledgeSearchAdapter:
        return BackendKnowledgeSearchAdapter(
            self.factory,
            self.personal if personal is None else personal,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )

    @staticmethod
    def _native_result(
        adapter: BackendKnowledgeSearchAdapter,
        principal: Principal,
        **arguments: object,
    ) -> list[dict[str, object]]:
        value = KnowledgeSearchInput(**arguments)
        context = ToolExecutionContext(
            principal,
            "knowledge-adapter-conformance",
            "knowledge-call",
            KnowledgeSearchDependencies(adapter, "demo-tenant"),
        )
        return knowledge_search_handler(value, context).data

    @staticmethod
    def _legacy_result(
        factory: ConformanceFactory,
        personal: ConformancePersonal,
        principal: Principal,
        **arguments: object,
    ) -> list[dict]:
        source_types = arguments.pop("source_types", None)
        with (
            patch.object(rag, "current_principal", return_value=principal),
            patch.object(rag, "get_factory_search_backend", return_value=factory),
            patch.object(
                rag,
                "search_personal_knowledge",
                side_effect=lambda owner, query, limit: list(
                    personal.search(principal, owner, query, limit).rows
                ),
            ),
            patch.object(
                rag,
                "get_settings",
                return_value=SimpleNamespace(factory_search_backend="fixture"),
            ),
        ):
            return rag.search_agent_knowledge(
                source_types=list(source_types) if source_types is not None else None,
                **arguments,
            )

    def test_factory_and_personal_receive_exact_principal_requests_and_owner(
        self,
    ) -> None:
        query = KnowledgeSearchQuery("LITHO 颗粒", limit=7)
        snapshot = self.adapter().fetch(query, self.principal)
        self.assertIs(self.factory.alias_calls[0], self.principal)
        self.assertIs(self.factory.search_calls[0][0], self.principal)
        request = self.factory.search_calls[0][1]
        self.assertEqual(
            (request.inferred_filters, request.candidate_limit, request.source_types),
            (
                {
                    "process_step": "LITHO",
                    "equipment_id": None,
                    "defect_type": "Particles",
                },
                35,
                ("knowledge", "case"),
            ),
        )
        self.assertEqual(
            self.personal.calls[0][1:],
            (
                "demo-user",
                "LITHO 颗粒 LITHO Particles photolithography lithography introduction intro overview purpose principle fundamentals basics process photoresist exposure reticle mask",
                35,
            ),
        )
        self.assertEqual(snapshot.owner_user_id, "demo-user")
        self.assertEqual(
            [source.source_ref for source in snapshot.sources],
            ["backend:knowledge-search/factory", "backend:knowledge-search/personal"],
        )
        self.assertTrue(
            all(
                source.scope == knowledge_scope(self.principal)
                for source in snapshot.sources
            )
        )

    def test_nondefault_tenant_owner_mapping_and_factory_only_selection(self) -> None:
        principal = Principal("tenant-b", "engineer")
        adapter = BackendKnowledgeSearchAdapter(
            self.factory,
            self.personal,
            demo_tenant_id="tenant-b",
            default_tenant_id="demo-tenant",
        )
        query = KnowledgeSearchQuery("LITHO", source_types=("knowledge",))
        snapshot = adapter.fetch(query, principal)
        self.assertIsNone(snapshot.owner_user_id)
        self.assertEqual(self.personal.calls, [])
        self.assertEqual(len(snapshot.sources), 1)
        self.personal.batch = PersonalSearchBatch("tenant-b:engineer", ())
        snapshot = adapter.fetch(KnowledgeSearchQuery("LITHO"), principal)
        self.assertEqual(snapshot.owner_user_id, "tenant-b:engineer")
        self.assertEqual(self.personal.calls[-1][1], "tenant-b:engineer")

    def test_personal_only_still_queries_factory_with_legacy_factory_sources(
        self,
    ) -> None:
        query = KnowledgeSearchQuery("LITHO", source_types=("personal",))
        self.adapter().fetch(query, self.principal)
        request = self.factory.search_calls[0][1]
        self.assertEqual(request.source_types, ("knowledge", "case"))
        self.assertEqual(len(self.personal.calls), 1)

    def test_tenant_and_missing_personal_fail_before_source_calls(self) -> None:
        adapter = self.adapter()
        with self.assertRaises(KnowledgeSearchDataError):
            adapter.fetch(KnowledgeSearchQuery("LITHO"), self.other_tenant)
        self.assertEqual(
            (self.factory.alias_calls, self.factory.search_calls, self.personal.calls),
            ([], [], []),
        )
        missing = BackendKnowledgeSearchAdapter(
            self.factory,
            None,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )
        with self.assertRaises(KnowledgeSearchDataError):
            missing.fetch(KnowledgeSearchQuery("LITHO"), self.principal)
        self.assertEqual(
            (self.factory.alias_calls, self.factory.search_calls), ([], [])
        )

    def test_bad_personal_owner_and_bad_factory_rows_are_sanitized(self) -> None:
        self.personal.batch = PersonalSearchBatch("other", ())
        with self.assertRaisesRegex(KnowledgeSearchDataError, "unavailable"):
            self.adapter().fetch(KnowledgeSearchQuery("LITHO"), self.principal)
        self.factory.rows = [
            {"source_type": "case", "reference_id": "CASE-1", "case_status": "Draft"}
        ]
        self.personal.batch = PersonalSearchBatch("demo-user", ())
        with self.assertRaisesRegex(KnowledgeSearchDataError, "unavailable"):
            self.adapter().fetch(
                KnowledgeSearchQuery("LITHO", source_types=("knowledge",)),
                self.principal,
            )

    def test_timeout_and_failures_are_sanitized_once_without_fallback(self) -> None:
        class TimeoutFactory(RecordingFactory):
            def defect_aliases(self, principal: Principal) -> object:
                self.alias_calls.append(principal)
                raise TimeoutError("private endpoint")

        timed = TimeoutFactory()
        adapter = BackendKnowledgeSearchAdapter(
            timed,
            self.personal,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )
        with self.assertRaisesRegex(KnowledgeSearchTimeoutError, "timed out"):
            adapter.fetch(KnowledgeSearchQuery("LITHO"), self.principal)
        self.assertEqual(len(timed.alias_calls), 1)
        self.assertEqual(timed.search_calls, [])

        class FailingFactory(RecordingFactory):
            def defect_aliases(self, principal: Principal) -> object:
                self.alias_calls.append(principal)
                raise KnowledgeSearchDataError("private factory details")

        failing = FailingFactory()
        adapter = BackendKnowledgeSearchAdapter(
            failing,
            self.personal,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )
        with self.assertRaisesRegex(KnowledgeSearchDataError, "unavailable"):
            adapter.fetch(KnowledgeSearchQuery("LITHO"), self.principal)
        self.assertEqual(len(failing.alias_calls), 1)

    def test_fake_is_exact_copied_and_requires_fake_sources(self) -> None:
        query = KnowledgeSearchQuery("LITHO", source_types=("knowledge",))
        source = ToolSource(
            "fake:knowledge",
            "fixture",
            ToolSourceKind.FAKE,
            knowledge_scope(self.principal),
        )
        snapshot = KnowledgeSearchSnapshot(
            query, "demo-tenant", "demo-user", None, {}, (), (source,)
        )
        adapter = FakeKnowledgeSearchAdapter(
            "demo-tenant", "demo-user", {query: snapshot}
        )
        result = adapter.fetch(query, self.principal)
        self.assertEqual(result, snapshot)
        self.assertIsNot(result, snapshot)
        self.assertEqual(adapter.calls, [query])
        with self.assertRaises(KnowledgeSearchDataError):
            adapter.fetch(
                KnowledgeSearchQuery("ETCH", source_types=("knowledge",)),
                self.principal,
            )
        self.assertEqual(len(adapter.calls), 2)
        non_fake = ToolSource(
            "provider:knowledge",
            "provider",
            ToolSourceKind.SQLITE,
            knowledge_scope(self.principal),
        )
        with self.assertRaises(ValueError):
            FakeKnowledgeSearchAdapter(
                "demo-tenant",
                "demo-user",
                {
                    query: KnowledgeSearchSnapshot(
                        query,
                        "demo-tenant",
                        "demo-user",
                        None,
                        {},
                        (),
                        (non_fake,),
                    )
                },
            )

    def test_configuration_fails_fast(self) -> None:
        with self.assertRaises(ValueError):
            BackendKnowledgeSearchAdapter(
                self.factory,
                self.personal,
                demo_tenant_id="",
                default_tenant_id="demo-tenant",
            )
        with self.assertRaises(ValueError):
            BackendKnowledgeSearchAdapter(
                object(),
                self.personal,
                demo_tenant_id="demo-tenant",
                default_tenant_id="demo-tenant",
            )
        with self.assertRaises(TypeError):
            BackendKnowledgeSearchAdapter(
                self.factory,
                self.personal,
                demo_tenant_id="demo-tenant",
                default_tenant_id="demo-tenant",
                source_kind="fake",
            )

    def test_native_handler_matches_legacy_agent_search_for_full_output_matrix(
        self,
    ) -> None:
        cases = (
            {"query": "LITHO 颗粒", "limit": 1},
            {"query": "LITHO 颗粒", "limit": 2},
            {"query": "LITHO 颗粒", "limit": 5},
            {"query": "LITHO 颗粒", "limit": 10},
            {
                "query": "particle review",
                "process_step": "LITHO",
                "equipment_id": "LITHO-01",
                "defect_type": "Particles",
                "limit": 5,
            },
        )
        source_subsets = (
            ("personal",),
            ("knowledge",),
            ("case",),
            ("personal", "knowledge"),
            ("personal", "case"),
            ("knowledge", "case"),
            ("personal", "knowledge", "case"),
        )
        for principal in (self.principal, Principal("tenant-b", "engineer")):
            for source_types in source_subsets:
                for case in cases:
                    with self.subTest(
                        tenant=principal.tenant_id,
                        source_types=source_types,
                        case=case,
                    ):
                        factory = ConformanceFactory()
                        personal = ConformancePersonal()
                        adapter = BackendKnowledgeSearchAdapter(
                            factory,
                            personal,
                            demo_tenant_id=principal.tenant_id,
                            default_tenant_id="demo-tenant",
                        )
                        arguments = {**case, "source_types": source_types}
                        native = self._native_result(adapter, principal, **arguments)
                        legacy = self._legacy_result(
                            factory, personal, principal, **arguments
                        )
                        self.assertEqual(native, legacy)
                        if "personal" in source_types:
                            self.assertEqual(
                                personal.calls[-1][1], principal.knowledge_owner_id
                            )
                        else:
                            self.assertEqual(personal.calls, [])

    def test_tokenless_input_contacts_neither_adapter_nor_legacy_source(self) -> None:
        factory = ConformanceFactory()
        personal = ConformancePersonal()
        adapter = BackendKnowledgeSearchAdapter(
            factory,
            personal,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )
        for query in ("", "   ", "？！"):
            with self.subTest(query=query):
                self.assertEqual(
                    self._native_result(adapter, self.principal, query=query), []
                )
                self.assertEqual(
                    self._legacy_result(factory, personal, self.principal, query=query),
                    [],
                )
        self.assertEqual(factory.alias_calls, [])
        self.assertEqual(factory.search_calls, [])
        self.assertEqual(personal.calls, [])

    def test_fake_constructor_and_fetch_deeply_isolate_nested_fixture_data(
        self,
    ) -> None:
        query = KnowledgeSearchQuery("LITHO", source_types=("knowledge",))
        source = ToolSource(
            "fake:knowledge",
            "fixture",
            ToolSourceKind.FAKE,
            knowledge_scope(self.principal),
        )
        snapshot = KnowledgeSearchSnapshot(
            query,
            "demo-tenant",
            "demo-user",
            None,
            {"Particles": ("颗粒",)},
            (
                {
                    "source_type": "knowledge",
                    "reference_id": "KB-1",
                    "nested": {"values": ["before"]},
                },
            ),
            (source,),
        )
        fixtures = {query: snapshot}
        adapter = FakeKnowledgeSearchAdapter("demo-tenant", "demo-user", fixtures)
        fixtures[query].candidates[0]["nested"]["values"].append("constructor")
        returned = adapter.fetch(query, self.principal)
        returned.candidates[0]["nested"]["values"].append("fetch")
        self.assertEqual(
            adapter.fetch(query, self.principal).candidates[0]["nested"],
            {"values": ["before"]},
        )

    def test_batch_type_owner_and_tenant_violations_fail_closed(self) -> None:
        adapter = self.adapter()
        for batch in (
            object(),
            PersonalSearchBatch("other", ()),
            PersonalSearchBatch(
                "demo-user",
                (
                    {
                        "source_type": "personal",
                        "reference_id": "PERSONAL-1",
                        "owner_user_id": "other",
                    },
                ),
            ),
            PersonalSearchBatch(
                "demo-user",
                (
                    {
                        "source_type": "personal",
                        "reference_id": "PERSONAL-1",
                        "tenant_id": "other",
                    },
                ),
            ),
        ):
            with self.subTest(batch=batch):
                self.personal.batch = batch
                with self.assertRaisesRegex(KnowledgeSearchDataError, "unavailable"):
                    adapter.fetch(KnowledgeSearchQuery("LITHO"), self.principal)

    def test_factory_only_query_succeeds_without_personal_port(self) -> None:
        adapter = BackendKnowledgeSearchAdapter(
            self.factory,
            None,
            demo_tenant_id="demo-tenant",
            default_tenant_id="demo-tenant",
        )
        snapshot = adapter.fetch(
            KnowledgeSearchQuery("LITHO", source_types=("knowledge",)),
            self.principal,
        )
        self.assertIsNone(snapshot.owner_user_id)
        self.assertEqual(len(snapshot.sources), 1)

    def test_every_source_stage_sanitizes_builtin_and_typed_timeouts_once(self) -> None:
        stages = ("aliases", "search", "personal")
        exceptions = (
            TimeoutError("private builtin"),
            KnowledgeSearchTimeoutError("private typed"),
        )
        for stage in stages:
            for error in exceptions:
                with self.subTest(stage=stage, error=type(error).__name__):
                    factory = RecordingFactory()
                    personal = RecordingPersonal()
                    calls = {"aliases": 0, "search": 0, "personal": 0}
                    original_aliases = factory.defect_aliases
                    original_search = factory.search
                    original_personal = personal.search

                    def aliases(
                        principal: Principal,
                        *,
                        calls: dict[str, int] = calls,
                        stage: str = stage,
                        error: Exception = error,
                        original_aliases: object = original_aliases,
                    ) -> object:
                        calls["aliases"] += 1
                        if stage == "aliases":
                            raise error
                        return original_aliases(principal)

                    def search(
                        principal: Principal,
                        request: object,
                        *,
                        calls: dict[str, int] = calls,
                        stage: str = stage,
                        error: Exception = error,
                        original_search: object = original_search,
                    ) -> object:
                        calls["search"] += 1
                        if stage == "search":
                            raise error
                        return original_search(principal, request)

                    def personal_search(
                        principal: Principal,
                        owner: str,
                        query: str,
                        limit: int,
                        *,
                        calls: dict[str, int] = calls,
                        stage: str = stage,
                        error: Exception = error,
                        original_personal: object = original_personal,
                    ) -> object:
                        calls["personal"] += 1
                        if stage == "personal":
                            raise error
                        return original_personal(principal, owner, query, limit)

                    factory.defect_aliases = aliases
                    factory.search = search
                    personal.search = personal_search
                    adapter = BackendKnowledgeSearchAdapter(
                        factory,
                        personal,
                        demo_tenant_id="demo-tenant",
                        default_tenant_id="demo-tenant",
                    )
                    query = KnowledgeSearchQuery(
                        "LITHO",
                        source_types=("knowledge",)
                        if stage != "personal"
                        else ("personal",),
                    )
                    with self.assertRaisesRegex(
                        KnowledgeSearchTimeoutError, "timed out"
                    ) as raised:
                        adapter.fetch(query, self.principal)
                    self.assertNotIn("private", str(raised.exception))
                    self.assertEqual(calls[stage], 1)
                    if stage == "aliases":
                        self.assertEqual(calls["search"], 0)
                        self.assertEqual(calls["personal"], 0)
                    elif stage == "search":
                        self.assertEqual(calls["personal"], 0)


if __name__ == "__main__":
    unittest.main()
