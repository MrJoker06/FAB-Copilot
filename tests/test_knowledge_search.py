from __future__ import annotations

import math
import tempfile
import unittest
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from app.knowledge.ranking import _metadata_rerank
from app.tools.knowledge_search.binding import create_knowledge_search_binding
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchInput,
    KnowledgeSearchInputError,
    KnowledgeSearchQuery,
    KnowledgeSearchSnapshot,
    knowledge_owner_id,
    knowledge_scope,
    validate_knowledge_search_output,
)
from app.tools.knowledge_search.handler import KnowledgeSearchDependencies
from scripts.check_module_boundaries import boundary_errors, load_manifest


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("analyst",)


class Port:
    def __init__(self, snapshot: KnowledgeSearchSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch(
        self, query: KnowledgeSearchQuery, principal: Principal
    ) -> KnowledgeSearchSnapshot:
        self.calls += 1
        return self.snapshot


class KnowledgeSearchTests(unittest.TestCase):
    principal = Principal()

    def query(self) -> KnowledgeSearchQuery:
        return KnowledgeSearchInput(
            "CMP particle guide", process_step="cmp", equipment_id="cmp-01"
        ).resolve()

    def rows(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "source_type": "knowledge",
                "reference_id": "KB-1",
                "status": "Active",
                "title": "CMP particle guide",
                "section": "Guide",
                "process_steps": "CMP",
                "authority": 5,
                "tags": "particle",
            },
            {
                "source_type": "case",
                "reference_id": "CASE-1",
                "case_status": "Validated",
                "title": "CMP particle case",
                "process_step": "CMP",
                "equipment_family": "CMP",
                "equipment_id": "CMP-01",
                "defect_type": "Particle",
                "root_cause_confidence": 0.9,
                "occurred_date": "2025-01-01",
            },
            {
                "source_type": "personal",
                "reference_id": "PERSONAL-1",
                "title": "My CMP notes",
                "process_steps": ["CMP"],
                "equipment_ids": ["CMP-01"],
                "tags": ["particle"],
                "owner_user_id": "engineer",
            },
        )

    def snapshot(
        self, query: KnowledgeSearchQuery | None = None
    ) -> KnowledgeSearchSnapshot:
        query = query or self.query()
        return KnowledgeSearchSnapshot(
            query,
            "demo",
            "engineer",
            "engineer" if "personal" in query.source_types else None,
            {"Particle": ("particle",)},
            self.rows(),
            (
                ToolSource(
                    "fake:knowledge",
                    "test",
                    ToolSourceKind.FAKE,
                    knowledge_scope(self.principal),
                ),
            ),
        )

    def context(self, port: Port) -> ToolExecutionContext[KnowledgeSearchDependencies]:
        return ToolExecutionContext(
            self.principal,
            "run",
            "call",
            KnowledgeSearchDependencies(port, "demo"),
        )

    def binding(self, port: Port):
        return create_knowledge_search_binding(port, default_tenant_id="demo")

    def test_input_is_closed_and_normalized(self) -> None:
        value = KnowledgeSearchInput.from_arguments(
            {
                "query": " CMP particle ",
                "limit": 2,
                "process_step": "cmp",
                "equipment_id": "cmp-01",
                "source_types": ["knowledge", "case"],
            }
        )
        self.assertEqual(
            value.resolve(),
            KnowledgeSearchQuery(
                "CMP particle", 2, "CMP", "CMP-01", None, ("knowledge", "case")
            ),
        )
        for arguments in (
            {},
            {"query": None},
            {"query": "x", "sql": "select 1"},
            {"query": "x", "source_types": ["knowledge", "knowledge"]},
            {"query": "x", "source_types": []},
            {"query": "x", "source_types": "knowledge"},
            {"query": "x", "limit": True},
            {"query": "x", "limit": 11},
            {"query": "x", "process_step": []},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(KnowledgeSearchInputError),
            ):
                KnowledgeSearchInput.from_arguments(arguments)

    def test_handler_preserves_existing_ranking_and_prepare_identity(self) -> None:
        query = self.query()
        port = Port(self.snapshot(query))
        binding = self.binding(port)
        value = KnowledgeSearchInput(
            "CMP particle guide", process_step="CMP", equipment_id="CMP-01"
        )
        prepared = binding.prepare(value, self.context(port))
        self.assertIs(prepared.input_value, value)
        self.assertEqual(prepared.scope, knowledge_scope(self.principal))
        result = binding.handler(value, self.context(port))
        expected = _metadata_rerank(
            deepcopy(list(self.rows())),
            {
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "defect_type": "Particle",
            },
            5,
            ["personal", "knowledge", "case"],
        )
        self.assertEqual(result.data, expected)
        self.assertEqual(result.row_count, len(expected))
        self.assertEqual(port.calls, 1)
        self.assertNotIn("retrieval", port.snapshot.candidates[0])

    def test_tokenless_query_has_no_source_call(self) -> None:
        query = KnowledgeSearchInput("?!").resolve()
        port = Port(self.snapshot(query))
        value = KnowledgeSearchInput("?!")
        binding = self.binding(port)
        self.assertEqual(
            binding.prepare(value, self.context(port)).scope.tenant_id,
            self.principal.tenant_id,
        )
        self.assertIsNone(binding.prepare(value, self.context(port)).scope.grain)
        result = binding.handler(value, self.context(port))
        self.assertEqual(
            (result.data, result.row_count, result.sources, port.calls), ([], 0, (), 0)
        )

    def test_snapshot_identity_owner_scope_and_rows_fail_closed(self) -> None:
        query = self.query()
        cases = (
            replace(self.snapshot(query), tenant_id="other"),
            replace(self.snapshot(query), user_id="other"),
            replace(
                self.snapshot(query), query=KnowledgeSearchInput("other").resolve()
            ),
            replace(self.snapshot(query), owner_user_id="other"),
            replace(self.snapshot(query), sources=()),
            replace(
                self.snapshot(query),
                sources=(
                    ToolSource(
                        "fake:wrong-scope",
                        "test",
                        ToolSourceKind.FAKE,
                        ToolScope("demo"),
                    ),
                ),
            ),
            replace(self.snapshot(query), aliases={"Particle": ("",)}),
            replace(
                self.snapshot(query),
                candidates=(
                    {
                        "source_type": "knowledge",
                        "reference_id": "",
                        "status": "Active",
                    },
                ),
            ),
        )
        for snapshot in cases:
            port = Port(snapshot)
            with (
                self.subTest(snapshot=snapshot),
                self.assertRaises(KnowledgeSearchDataError),
            ):
                self.binding(port).handler(
                    KnowledgeSearchInput(
                        "CMP particle guide", process_step="CMP", equipment_id="CMP-01"
                    ),
                    self.context(port),
                )

    def test_wrong_personal_owner_and_nonfinite_candidate_fail_closed(self) -> None:
        query = self.query()
        rows = list(self.rows())
        rows[2] = dict(rows[2], owner_user_id="other")
        wrong_owner = replace(self.snapshot(query), candidates=tuple(rows))
        rows = list(self.rows())
        rows[1] = dict(rows[1], root_cause_confidence=math.nan)
        nonfinite = replace(self.snapshot(query), candidates=tuple(rows))
        rows = list(self.rows())
        rows[0] = dict(rows[0], owner_user_id="other")
        factory_owner = replace(self.snapshot(query), candidates=tuple(rows))
        rows = list(self.rows())
        rows[0] = dict(rows[0], score=math.nan)
        raw_nan = replace(self.snapshot(query), candidates=tuple(rows))
        rows = list(self.rows())
        rows[0] = dict(rows[0], adapter_extra=object())
        unsafe_extra = replace(self.snapshot(query), candidates=tuple(rows))
        for snapshot in (
            wrong_owner,
            nonfinite,
            factory_owner,
            raw_nan,
            unsafe_extra,
        ):
            port = Port(snapshot)
            with (
                self.subTest(snapshot=snapshot),
                self.assertRaises(KnowledgeSearchDataError),
            ):
                self.binding(port).handler(
                    KnowledgeSearchInput(
                        "CMP particle guide", process_step="CMP", equipment_id="CMP-01"
                    ),
                    self.context(port),
                )

    def test_owner_resolution_does_not_use_principal_property(self) -> None:
        self.assertEqual(knowledge_owner_id(self.principal, "demo"), "engineer")
        self.assertEqual(
            knowledge_owner_id(Principal("t2", "engineer"), "demo"), "t2:engineer"
        )

    def test_non_default_tenant_personal_owner_and_user_are_distinct(self) -> None:
        principal = Principal("t2", "engineer")
        query = KnowledgeSearchInput("CMP notes", source_types=("personal",)).resolve()
        rows = (
            {
                "source_type": "personal",
                "reference_id": "PERSONAL-2",
                "title": "CMP notes",
                "process_steps": ["CMP"],
                "equipment_ids": [],
                "tags": [],
                "tenant_id": "t2",
                "user_id": "engineer",
                "owner_user_id": "t2:engineer",
            },
        )
        snapshot = KnowledgeSearchSnapshot(
            query,
            "t2",
            "engineer",
            "t2:engineer",
            {},
            rows,
            (
                ToolSource(
                    "fake:personal",
                    "test",
                    ToolSourceKind.FAKE,
                    knowledge_scope(principal),
                ),
            ),
        )
        port = Port(snapshot)
        context = ToolExecutionContext(
            principal, "run", "call", KnowledgeSearchDependencies(port, "demo")
        )
        result = create_knowledge_search_binding(
            port, default_tenant_id="demo"
        ).handler(
            KnowledgeSearchInput("CMP notes", source_types=("personal",)), context
        )
        self.assertEqual(result.data[0]["reference_id"], "PERSONAL-2")

    def test_output_validator_rejects_unhashable_or_dishonest_metadata(self) -> None:
        base = {
            "source_type": "knowledge",
            "reference_id": "KB-1",
            "status": "Active",
            "retrieval": {
                "lexical_rank": 1,
                "final_score": 1.0,
                "confidence": "high",
                "selection_reason": ["fixture"],
                "filters": {
                    "process_step": None,
                    "equipment_id": None,
                    "defect_type": None,
                },
            },
        }
        for row in (
            dict(base, source_type=[]),
            dict(base, status="Draft"),
            dict(base, retrieval=dict(base["retrieval"], confidence=[])),
            dict(
                base,
                retrieval=dict(
                    base["retrieval"],
                    filters={
                        "process_step": [],
                        "equipment_id": None,
                        "defect_type": None,
                    },
                ),
            ),
        ):
            with self.subTest(row=row), self.assertRaises(KnowledgeSearchDataError):
                validate_knowledge_search_output([row])

    def test_knowledge_tool_boundary_exceptions_are_contract_specific(self) -> None:
        allowed_edges = {
            (
                "app.tools.knowledge_search.binding",
                "app.agent_runtime.tools.contracts",
            ),
            (
                "app.tools.knowledge_search.binding",
                "app.agent_runtime.tools.definition",
            ),
            (
                "app.tools.knowledge_search.contracts",
                "app.agent_runtime.tools.contracts",
            ),
            (
                "app.tools.knowledge_search.contracts",
                "app.agent_runtime.tools.dispatch_contracts",
            ),
            (
                "app.tools.knowledge_search.handler",
                "app.agent_runtime.tools.contracts",
            ),
        }
        manifest = deepcopy(load_manifest())
        exceptions = manifest["existing_edge_exceptions"]
        self.assertIsInstance(exceptions, list)
        selected = [
            edge
            for edge in exceptions
            if (edge["source"], edge["target"]) in allowed_edges
        ]
        self.assertEqual(
            {(edge["source"], edge["target"]) for edge in selected}, allowed_edges
        )
        self.assertTrue(
            all(
                "*" not in edge["source"] and "*" not in edge["target"]
                for edge in selected
            )
        )
        manifest["root_modules"] = {}
        manifest["existing_edge_exceptions"] = selected
        with tempfile.TemporaryDirectory() as raw:
            app_dir = Path(raw) / "app"
            tool_dir = app_dir / "tools" / "knowledge_search"
            tool_dir.mkdir(parents=True)
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (tool_dir / "binding.py").write_text(
                "from app.agent_runtime.tools.contracts import ToolScope\n"
                "from app.agent_runtime.tools.definition import ToolBinding\n",
                encoding="utf-8",
            )
            (tool_dir / "contracts.py").write_text(
                "from app.agent_runtime.tools.contracts import ToolPrincipal\n"
                "from app.agent_runtime.tools.dispatch_contracts import ToolInputError\n",
                encoding="utf-8",
            )
            handler = tool_dir / "handler.py"
            base_handler = "from app.agent_runtime.tools.contracts import ToolResult\n"
            handler.write_text(base_handler, encoding="utf-8")
            self.assertEqual(boundary_errors(app_dir, manifest), [])
            for target in (
                "app.agent_runtime.execution.loop_guard",
                "app.agent_runtime.service",
                "app.agent_runtime.tools.registry",
                "app.core.settings",
                "app.core.identity",
                "app.knowledge.rag",
                "app.knowledge.search_registry",
                "app.persistence.database",
                "socket",
            ):
                with self.subTest(target=target):
                    handler.write_text(
                        f"{base_handler}import {target}\n", encoding="utf-8"
                    )
                    errors = boundary_errors(app_dir, manifest)
                    self.assertEqual(len(errors), 1)
                    self.assertTrue(
                        errors[0].startswith("app.tools.knowledge_search.handler:2:")
                    )


if __name__ == "__main__":
    unittest.main()
