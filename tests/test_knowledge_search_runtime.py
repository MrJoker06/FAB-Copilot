"""Ready and Loop acceptance tests for the bounded knowledge-search demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import unittest
from unittest.mock import patch

from app.agent_runtime.execution.runtime_contracts import ModelRequest
from app.bootstrap import knowledge_search_demo as demo
from app.tools.knowledge_search.backend_search import BackendKnowledgeSearchAdapter
from app.demo_data.tool_sources.knowledge_search import FakeKnowledgeSearchAdapter
from app.tools.knowledge_search.contracts import KnowledgeSearchDataError


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "mode": "ready",
        "adapter": "fake",
        "tenant_id": "demo",
        "source_tenant_id": "demo",
        "user_id": "demo-user",
        "source_user_id": "demo-user",
        "default_tenant_id": "demo",
        "role": "analyst",
        "tool": "search_knowledge",
        "arguments": '{"query":"LITHO 颗粒"}',
        "timeout_ms": 1000,
        "max_tool_calls": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _scope() -> dict[str, object]:
    return {
        "tenant_id": "demo",
        "start": None,
        "end": None,
        "equipment_ids": [],
        "process_steps": [],
        "lot_ids": [],
        "grain": "knowledge_search",
    }


def _expected_default(owner: str = "demo-user") -> list[dict[str, object]]:
    filters = {
        "process_step": "LITHO",
        "equipment_id": None,
        "defect_type": "Particles",
    }
    return [
        {
            "source_type": "personal",
            "reference_id": "PERSONAL-1",
            "owner_user_id": owner,
            "title": "My LITHO particle notes",
            "section": "Notes",
            "process_steps": ["LITHO"],
            "equipment_ids": ["LITHO-01"],
            "tags": ["Particles"],
            "excerpt": "particle notes",
            "retrieval": {
                "lexical_rank": 1,
                "final_score": 6.3393,
                "confidence": "high",
                "selection_reason": [
                    "personal lexical rank 1",
                    "current user private knowledge",
                    "process=LITHO",
                    "defect=Particles",
                ],
                "filters": filters,
            },
        },
        {
            "source_type": "case",
            "reference_id": "CASE-LITHO-1",
            "case_status": "Validated",
            "title": "Particle recovery",
            "source": "历史案例库",
            "section": "Particle recovery",
            "process_step": "LITHO",
            "equipment_id": "LITHO-01",
            "equipment_family": "LITHO",
            "defect_type": "Particles",
            "root_cause_confidence": 0.9,
            "occurred_date": "2020-01-01",
            "retrieval": {
                "lexical_rank": 1,
                "final_score": 5.4593,
                "confidence": "high",
                "selection_reason": [
                    "case lexical rank 1",
                    "process=LITHO",
                    "defect=Particles",
                    "validated confidence=0.90",
                ],
                "filters": filters,
            },
        },
        {
            "source_type": "knowledge",
            "reference_id": "KB-LITHO-1",
            "status": "Active",
            "title": "LITHO particle guide",
            "section": "Overview",
            "process_steps": "LITHO",
            "authority": 5,
            "tags": "Particles",
            "score": -1.0,
            "retrieval": {
                "lexical_rank": 1,
                "final_score": 5.2393,
                "confidence": "high",
                "selection_reason": [
                    "knowledge lexical rank 1",
                    "process=LITHO",
                    "authority=5/5",
                    "defect=Particles",
                ],
                "filters": filters,
            },
        },
    ]


class KnowledgeSearchRuntimeTests(unittest.TestCase):
    def run_demo(self, **overrides: object) -> dict[str, object]:
        return asyncio.run(demo._run(_args(**overrides)))

    def test_full_result_across_adapters_modes_and_source_sets(self) -> None:
        expected = _expected_default()
        cases = (
            ('{"query":"LITHO 颗粒"}', expected),
            ('{"query":"LITHO 颗粒","source_types":["knowledge"]}', [expected[2]]),
            ('{"query":"LITHO 颗粒","source_types":["case"]}', [expected[1]]),
            ('{"query":"LITHO 颗粒","source_types":["personal"]}', [expected[0]]),
            ('{"query":"LITHO 颗粒","limit":2}', [expected[0], expected[2]]),
        )
        for adapter in ("fake", "backend"):
            for mode in ("ready", "loop"):
                for arguments, expected_data in cases:
                    with self.subTest(adapter=adapter, mode=mode, arguments=arguments):
                        payload = self.run_demo(
                            adapter=adapter, mode=mode, arguments=arguments
                        )
                        result = payload["typed_results"][0]
                        self.assertEqual(
                            (
                                result["tool"],
                                result["version"],
                                result["status"],
                                result["state"],
                                result["row_count"],
                            ),
                            (
                                "search_knowledge",
                                "1.0.0",
                                "succeeded",
                                "completed",
                                len(expected_data),
                            ),
                        )
                        self.assertEqual(result["data"], expected_data)
                        self.assertEqual(result["error"], None)
                        self.assertEqual(payload["adapter_kind"], adapter)
                        self.assertEqual(
                            {
                                item["scope"]["grain"]
                                for item in payload["sources"].values()
                            },
                            {"knowledge_search"},
                        )
                        self.assertTrue(
                            all(
                                item["scope"] == _scope()
                                for item in payload["sources"].values()
                            )
                        )
                        self.assertEqual(
                            {
                                item["source_kind"]
                                for item in payload["sources"].values()
                            },
                            {"fake"},
                        )
                        self.assertEqual(
                            payload["observations"][0]["source_ref"], "TOOL:S01"
                        )
                        self.assertEqual(
                            payload["observations"][0]["result"], result["data"]
                        )
                        self.assertEqual(
                            payload["guard"]["per_tool_calls"], {"search_knowledge": 1}
                        )
                        self.assertEqual(payload["plan"]["budget"]["max_tool_calls"], 1)
                        self.assertEqual(
                            payload["plan"]["steps"],
                            [
                                {
                                    "step_id": "S01",
                                    "tool": "search_knowledge",
                                    "depends_on": [],
                                }
                            ],
                        )
                        if mode == "loop":
                            self.assertEqual(
                                json.loads(payload["tool_messages"][0]["content"])[
                                    "data"
                                ],
                                result["data"],
                            )
                            self.assertEqual(payload["model_response_calls"], 2)
                        else:
                            self.assertEqual(payload["model_response_calls"], 0)

    def test_tokenless_input_succeeds_without_sources(self) -> None:
        originals = {
            "fake": FakeKnowledgeSearchAdapter.fetch,
            "backend": BackendKnowledgeSearchAdapter.fetch,
            "aliases": demo._FixtureFactory.defect_aliases,
            "search": demo._FixtureFactory.search,
            "personal": demo._FixturePersonal.search,
        }
        calls = dict.fromkeys(originals, 0)

        def wrap(name: str):
            def call(*args: object, **kwargs: object):
                calls[name] += 1
                return originals[name](*args, **kwargs)

            return call

        with (
            patch.object(FakeKnowledgeSearchAdapter, "fetch", wrap("fake")),
            patch.object(BackendKnowledgeSearchAdapter, "fetch", wrap("backend")),
            patch.object(demo._FixtureFactory, "defect_aliases", wrap("aliases")),
            patch.object(demo._FixtureFactory, "search", wrap("search")),
            patch.object(demo._FixturePersonal, "search", wrap("personal")),
        ):
            for arguments in ('{"query":""}', '{"query":"？！"}'):
                for adapter in ("fake", "backend"):
                    for mode in ("ready", "loop"):
                        with self.subTest(
                            arguments=arguments, adapter=adapter, mode=mode
                        ):
                            for key in calls:
                                calls[key] = 0
                            payload = self.run_demo(
                                adapter=adapter, mode=mode, arguments=arguments
                            )
                            result = payload["typed_results"][0]
                            self.assertEqual(
                                (
                                    result["status"],
                                    result["data"],
                                    result["row_count"],
                                ),
                                ("succeeded", [], 0),
                            )
                            self.assertEqual(payload["sources"], {})
                            self.assertEqual(calls, dict.fromkeys(calls, 0))

    def test_rejections_have_zero_adapter_and_underlying_calls(self) -> None:
        invalid = (
            '{"sql":"select 1","query":"LITHO"}',
            '{"query":"LITHO","cursor":"x"}',
            '{"query":"LITHO","owner":"other"}',
            '{"query":"LITHO","limit":true}',
            '{"query":"LITHO","limit":11}',
            '{"query":[]}',
            '{"query":"LITHO","source_types":["unknown"]}',
            '{"query":"LITHO","process_step":"unknown"}',
            '{"query":"LITHO","source_types":"knowledge"}',
            '{"query":"LITHO","source_types":[]}',
            '{"query":"LITHO","source_types":[true]}',
            '{"query":"LITHO","source_types":[null]}',
            '{"query":"LITHO","owner_user_id":"other"}',
            '{"query":"LITHO","tenant_id":"other"}',
            '{"query":"LITHO","backend":"sqlite"}',
            '{"query":"LITHO","model":"private"}',
            '{"query":"LITHO","defect_type":null}',
            '{"query":null}',
            '{"query":true}',
        )
        originals = {
            "fake": FakeKnowledgeSearchAdapter.fetch,
            "backend": BackendKnowledgeSearchAdapter.fetch,
            "aliases": demo._FixtureFactory.defect_aliases,
            "search": demo._FixtureFactory.search,
            "personal": demo._FixturePersonal.search,
        }
        calls = dict.fromkeys(originals, 0)

        def wrap(name: str):
            def call(*args: object, **kwargs: object):
                calls[name] += 1
                return originals[name](*args, **kwargs)

            return call

        with (
            patch.object(FakeKnowledgeSearchAdapter, "fetch", wrap("fake")),
            patch.object(BackendKnowledgeSearchAdapter, "fetch", wrap("backend")),
            patch.object(demo._FixtureFactory, "defect_aliases", wrap("aliases")),
            patch.object(demo._FixtureFactory, "search", wrap("search")),
            patch.object(demo._FixturePersonal, "search", wrap("personal")),
        ):
            cases = [
                (item, {}, "invalid_arguments", "validation") for item in invalid
            ] + [
                ('{"query":"LITHO"}', {"role": "viewer"}, "denied", "authorization"),
                (
                    '{"query":"LITHO"}',
                    {"tenant_id": "other"},
                    "denied",
                    "authorization",
                ),
                ('{"query":"LITHO"}', {"user_id": "other"}, "denied", "authorization"),
                (
                    '{"query":"LITHO"}',
                    {"tool": "query_manufacturing_data"},
                    "denied",
                    "authorization",
                ),
            ]
            for adapter in ("fake", "backend"):
                for mode in ("ready", "loop"):
                    for arguments, overrides, status, kind in cases:
                        with self.subTest(
                            adapter=adapter,
                            mode=mode,
                            arguments=arguments,
                            overrides=overrides,
                        ):
                            for key in calls:
                                calls[key] = 0
                            payload = self.run_demo(
                                adapter=adapter,
                                mode=mode,
                                arguments=arguments,
                                **overrides,
                            )
                            result = payload["typed_results"][0]
                            self.assertEqual(result["status"], status)
                            self.assertEqual(result["error"]["kind"], kind)
                            self.assertEqual(payload["adapter_kind"], adapter)
                            self.assertEqual(calls, dict.fromkeys(calls, 0))

    def test_source_faults_do_not_retry_or_leak(self) -> None:
        cases = (
            ("fake", FakeKnowledgeSearchAdapter, "fetch", '{"query":"LITHO"}'),
            ("backend", demo._FixtureFactory, "search", '{"query":"LITHO"}'),
            (
                "backend",
                demo._FixturePersonal,
                "search",
                '{"query":"LITHO","source_types":["personal"]}',
            ),
        )
        for mode in ("ready", "loop"):
            for adapter, target, method, arguments in cases:
                calls = 0

                def fail(*args: object, **kwargs: object):
                    nonlocal calls
                    calls += 1
                    raise KnowledgeSearchDataError("private fixture detail")

                with (
                    self.subTest(mode=mode, adapter=adapter),
                    patch.object(target, method, fail),
                ):
                    payload = self.run_demo(
                        mode=mode, adapter=adapter, arguments=arguments
                    )
                result = payload["typed_results"][0]
                self.assertEqual(calls, 1)
                self.assertEqual(
                    (result["status"], result["error"]["kind"]),
                    ("failed", "data_source"),
                )
                self.assertNotIn("private", result["error"]["public_message"])
                self.assertEqual(result["data"], None)
                self.assertEqual(payload["sources"], {})

    def test_loop_fixture_requires_matching_tool_message(self) -> None:
        model = demo._LoopModel("search_knowledge", '{"query":"LITHO"}')
        asyncio.run(model.complete(None, None))
        with self.assertRaisesRegex(AssertionError, "tool message"):
            asyncio.run(model.complete(ModelRequest("second", ()), None))


if __name__ == "__main__":
    unittest.main()
