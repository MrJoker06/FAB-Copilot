"""B3: page API, optional Agent tools and the result store agree on one analysis version."""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.system.support import isolated_system_environment

isolated_system_environment()

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolStatus  # noqa: E402
from app.agent_runtime.tools.dispatch_contracts import BudgetDecision  # noqa: E402
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy  # noqa: E402
from app.agent_runtime.tools.dispatcher import ToolDispatcher  # noqa: E402
from app.agent_runtime.tools.tool_registry import ToolRegistry  # noqa: E402
from app.bootstrap.lot_commonality_assembly import (  # noqa: E402
    ResultStoreAnalyses,
    lot_commonality_service,
)
from app.bootstrap.storage_identity_assembly import configured_result_store  # noqa: E402
from app.bootstrap.tool_definitions import BUSINESS_TOOL_DEFINITIONS  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.persistence.tool_result_store import ResultStoreLimits, ToolResultStore  # noqa: E402
from app.tools.lot_commonality.binding import (  # noqa: E402
    CREATE_TOOL,
    LOT_COMMONALITY_DEFINITIONS,
    MEMBERS_TOOL,
    RECORDS_TOOL,
    create_lot_commonality_bindings,
)
from app.tools.lot_commonality.contracts import LotHistory, LotHistoryBatch  # noqa: E402
from app.tools.lot_commonality.service import LotCommonalityService  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lot_commonality"
BASE = "/api/lot-commonality/analyses"
SHANGHAI = timezone(timedelta(hours=8))
SAMPLE_REF = "lca_0123456789abcdef0123456789abcdef"


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _Source:
    def __init__(self, document):
        self.document = document

    def fetch(self, lot_ids, principal):
        lots = {}
        for lot in self.document["lots"]:
            if lot["lot_id"] in lot_ids:
                passes = tuple(item for item in self.document["passes"] if item["lot_id"] == lot["lot_id"])
                lots[lot["lot_id"]] = LotHistory(lot["lot_id"], lot["wafer_count"], lot["coverage"], passes)
        return LotHistoryBatch(self.document["source"], "2026-11-21T10:00:00+08:00", lots)


class _Principal:
    def __init__(self, tenant_id, user_id, roles=("analyst",)):
        self.tenant_id, self.user_id, self.roles = tenant_id, user_id, roles


class _AllowBudget:
    def claim(self, name, decoded_arguments):
        return BudgetDecision(True)

    def record_result(self, name, data, success):
        return None


def _tools(service, tenant_id, *, session_id=None):
    registry = ToolRegistry()
    for binding in create_lot_commonality_bindings(service, session_id=session_id):
        registry.register_native(binding)
    names = frozenset(LOT_COMMONALITY_DEFINITIONS)
    return ToolDispatcher(
        run_id="run", registry=registry,
        policy=DemoToolPolicy(names, frozenset({"analyst"}), tenant_id),
        budget=_AllowBudget(), allowed_tools=names,
    )


def _call(dispatcher, principal, name, arguments):
    context = ToolExecutionContext(principal, "run", "call", object())
    return asyncio.run(dispatcher.dispatch(name, arguments, context))


def _normalize(body, ref):
    """Replace the server-issued reference and opaque cursor with sample placeholders."""
    text = json.dumps(body, ensure_ascii=False).replace(ref, SAMPLE_REF)
    value = json.loads(text)
    if isinstance(value.get("page"), dict) and value["page"].get("next_cursor"):
        value["page"]["next_cursor"] = "lcc_opaque_example_page_2"
    return value


class FixtureBackedApiTests(unittest.TestCase):
    """HTTP and tools over the configured result store, with the frozen B1 source."""

    @classmethod
    def setUpClass(cls):
        cls.examples = _json("contract_examples.json")
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)
        settings = get_settings()
        cls.tenant, cls.user = settings.enterprise_default_tenant_id, settings.enterprise_default_user_id

    def setUp(self):
        self.document = _json("source_passes.json")
        self.now = datetime(2026, 11, 21, 10, 0, tzinfo=SHANGHAI)
        self.store_factory = lambda: ResultStoreAnalyses(configured_result_store())
        self.service = LotCommonalityService(
            store_factory=lambda: self.store_factory(),
            source_factory=lambda: _Source(self.document),
            clock=lambda: self.now,
            display_timezone=SHANGHAI,
        )
        patcher = patch.object(main, "lot_commonality_service", lambda: self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.principal = _Principal(self.tenant, self.user)

    def example(self, name):
        return copy.deepcopy(self.examples["examples"][name])

    def create(self, body=None, headers=None):
        body = body if body is not None else self.example("create_analysis")["request"]
        return self.client.post(BASE, json=body, headers=headers or {})

    def test_http_flow_matches_frozen_examples(self):
        created = self.create()
        self.assertEqual(created.status_code, 200, created.text)
        ref = created.json()["analysis_ref"]
        self.assertRegex(ref, r"^lca_[a-f0-9]{32}$")
        self.assertNotEqual(ref, SAMPLE_REF)
        self.assertEqual(_normalize(created.json(), ref), self.example("create_analysis")["response"])
        read = self.client.get(f"{BASE}/{ref}")
        self.assertEqual(read.json(), created.json())

        for name in ("members_chamber_b", "members_chamber_b_rework_same_pass", "records_chamber_b"):
            with self.subTest(name):
                example = self.example(name)
                kind = "records" if name.startswith("records") else "members"
                response = self.client.post(f"{BASE}/{ref}/{kind}", json=example["request"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(_normalize(response.json(), ref), example["response"])

        first = self.example("members_path_etch_metrology_page_1")
        page_1 = self.client.post(f"{BASE}/{ref}/members", json=first["request"]).json()
        self.assertEqual(_normalize(page_1, ref), first["response"])
        second = self.example("members_path_etch_metrology_page_2")
        second["request"]["cursor"] = page_1["page"]["next_cursor"]
        page_2 = self.client.post(f"{BASE}/{ref}/members", json=second["request"]).json()
        self.assertEqual(_normalize(page_2, ref), second["response"])

    def test_tools_and_http_read_the_same_version(self):
        ref = self.create().json()["analysis_ref"]
        tools = _tools(self.service, self.tenant)
        for name, kind, tool in (
            ("members_chamber_b", "members", MEMBERS_TOOL),
            ("records_chamber_b", "records", RECORDS_TOOL),
        ):
            with self.subTest(name):
                request = self.example(name)["request"]
                http = self.client.post(f"{BASE}/{ref}/{kind}", json=request).json()
                result = _call(tools, self.principal, tool, {"analysis_ref": ref, **request})
                self.assertIs(result.status, ToolStatus.SUCCEEDED, result.error)
                self.assertEqual(result.data, http)

        created = _call(tools, self.principal, CREATE_TOOL, self.example("create_analysis")["request"])
        self.assertIs(created.status, ToolStatus.SUCCEEDED, created.error)
        tool_ref = created.data["analysis_ref"]
        self.assertNotEqual(tool_ref, ref)
        self.assertEqual(self.client.get(f"{BASE}/{tool_ref}").json(), created.data)
        self.assertEqual(created.sources[0].source_ref, tool_ref)
        self.assertEqual(created.sources[0].scope.lot_ids, tuple("ABCDEFGHJK"))

    def test_foreign_principals_and_roles_are_rejected(self):
        ref = self.create().json()["analysis_ref"]
        members = self.example("members_chamber_b")["request"]
        for headers in ({"x-user-id": "someone-else"}, {"x-tenant-id": "tenant-b"}):
            with self.subTest(headers=headers):
                for response in (
                    self.client.get(f"{BASE}/{ref}", headers=headers),
                    self.client.post(f"{BASE}/{ref}/members", json=members, headers=headers),
                ):
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json()["error_code"], "RESULT_UNAVAILABLE")
        missing = self.client.get(f"{BASE}/lca_{'f' * 32}")
        self.assertEqual((missing.status_code, missing.json()["error_code"]), (404, "RESULT_UNAVAILABLE"))
        viewer = self.client.get(f"{BASE}/{ref}", headers={"x-roles": "viewer"})
        self.assertEqual((viewer.status_code, viewer.json()["error_code"]), (403, "SCOPE_DENIED"))
        denied_create = self.create(headers={"x-roles": "viewer"})
        self.assertEqual(denied_create.status_code, 403)

        tools = _tools(self.service, self.tenant)
        foreign = _call(tools, _Principal(self.tenant, "someone-else"), MEMBERS_TOOL, {"analysis_ref": ref, **members})
        self.assertIs(foreign.status, ToolStatus.DENIED)
        self.assertEqual(foreign.error.code, "RESULT_UNAVAILABLE")
        self.assertIsNone(foreign.data)

    def test_cursor_is_bound_to_reference_query_and_signature(self):
        ref = self.create().json()["analysis_ref"]
        other_ref = self.create().json()["analysis_ref"]
        request = self.example("members_path_etch_metrology_page_1")["request"]
        cursor = self.client.post(f"{BASE}/{ref}/members", json=request).json()["page"]["next_cursor"]
        self.assertTrue(cursor.startswith("lcc_"))
        cases = {
            "other query": (ref, {**request, "limit": 3, "cursor": cursor}),
            "other status": (ref, {**request, "status": "hit", "cursor": cursor}),
            "other reference": (other_ref, {**request, "cursor": cursor}),
            "tampered": (ref, {**request, "cursor": cursor[:-1] + ("0" if cursor[-1] != "0" else "1")}),
            "foreign format": (ref, {**request, "cursor": "lcc_opaque_example_page_2"}),
        }
        for label, (target, body) in cases.items():
            with self.subTest(label):
                response = self.client.post(f"{BASE}/{target}/members", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error_code"], "RESULT_CURSOR_INVALID")
        tools = _tools(self.service, self.tenant)
        result = _call(tools, self.principal, MEMBERS_TOOL, {"analysis_ref": other_ref, **request, "cursor": cursor})
        self.assertIs(result.status, ToolStatus.INVALID_ARGUMENTS)
        self.assertEqual(result.error.code, "RESULT_CURSOR_INVALID")

    def test_page_versions_expire_after_seven_days(self):
        ref = self.create().json()["analysis_ref"]
        self.now += timedelta(days=7, seconds=-1)
        self.assertEqual(self.client.get(f"{BASE}/{ref}").status_code, 200)
        self.now += timedelta(seconds=1)
        expired = self.client.get(f"{BASE}/{ref}")
        self.assertEqual((expired.status_code, expired.json()["error_code"]), (404, "RESULT_UNAVAILABLE"))

    def test_requery_creates_a_new_version_and_keeps_the_old_one(self):
        first = self.create().json()
        chb = "ch:GATE/ETCH:ETCH-07/CH-B"
        old_counts = next(item for item in first["candidates"] if item["candidate_id"] == chb)["counts"]
        for item in self.document["passes"]:
            if item["lot_id"] == "C" and item["operation_key"] == "GATE/ETCH":
                item["chambers"] = [chamber for chamber in item["chambers"] if chamber["chamber"] != "CH-B"]
        second = self.create().json()
        self.assertNotEqual(second["analysis_ref"], first["analysis_ref"])
        new_counts = next(item for item in second["candidates"] if item["candidate_id"] == chb)["counts"]
        self.assertNotEqual(new_counts["main"], old_counts["main"])
        self.assertEqual(self.client.get(f"{BASE}/{first['analysis_ref']}").json(), first)
        request = self.example("members_chamber_b")["request"]
        old_members = self.client.post(f"{BASE}/{first['analysis_ref']}/members", json=request).json()
        self.assertEqual(old_members["counts"], old_counts["main"])

    def test_concurrent_analyses_stay_isolated(self):
        request = self.example("create_analysis")["request"]
        bodies = []
        for lots in (["A", "B", "C"], ["D", "E", "F", "G"]):
            body = copy.deepcopy(request)
            body["groups"] = [{"group_id": "main", "name": "组", "role": "primary", "lot_ids": lots}]
            bodies.append(body)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(lambda body: self.service.create(body, self.principal), bodies))
        self.assertNotEqual(created[0]["analysis_ref"], created[1]["analysis_ref"])
        for summary, body in zip(created, bodies):
            read = self.client.get(f"{BASE}/{summary['analysis_ref']}").json()
            self.assertEqual(read, summary)
            self.assertEqual(
                [state["lot_id"] for state in read["groups"][0]["lot_states"]], body["groups"][0]["lot_ids"]
            )

    def test_storage_quota_rejects_new_versions_without_losing_old_ones(self):
        path = configured_result_store().path
        limited = ToolResultStore(path, limits=ResultStoreLimits(analysis_owner_count=1))
        self.store_factory = lambda: ResultStoreAnalyses(limited)
        headers = {"x-user-id": "quota-user"}
        first = self.create(headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.create(headers=headers)
        self.assertEqual((second.status_code, second.json()["error_code"]), (507, "RESULT_STORAGE_LIMIT"))
        tools = _tools(self.service, self.tenant)
        blocked = _call(tools, _Principal(self.tenant, "quota-user"), CREATE_TOOL, self.example("create_analysis")["request"])
        self.assertIs(blocked.status, ToolStatus.BLOCKED)
        self.assertEqual(blocked.error.code, "RESULT_STORAGE_LIMIT")
        self.assertEqual(self.client.get(f"{BASE}/{first.json()['analysis_ref']}", headers=headers).status_code, 200)

    def test_input_rejections_keep_their_codes(self):
        error = copy.deepcopy(self.examples["errors"]["limit_exceeded"])
        error["request"] = self.example("create_analysis")["request"]
        error["request"]["groups"] = [
            {"group_id": "main", "name": "本次异常", "role": "primary", "lot_ids": [f"L{index:03d}" for index in range(201)]}
        ]
        response = self.client.post(BASE, json=error["request"])
        self.assertEqual(response.status_code, error["status"])
        self.assertEqual(response.json()["error_code"], error["response"]["error_code"])
        self.assertEqual(response.json()["context"], error["response"]["context"])
        tools = _tools(self.service, self.tenant)
        result = _call(tools, self.principal, CREATE_TOOL, error["request"])
        self.assertIs(result.status, ToolStatus.INVALID_ARGUMENTS)
        self.assertEqual(result.error.code, "ANALYSIS_LIMIT_EXCEEDED")
        malformed = _call(tools, self.principal, MEMBERS_TOOL, {"analysis_ref": "not-a-ref"})
        self.assertIs(malformed.status, ToolStatus.INVALID_ARGUMENTS)


class DefaultAssemblyTests(unittest.TestCase):
    """The shipped composition: local manufacturing SQLite and the configured result store."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)
        settings = get_settings()
        cls.tenant, cls.user = settings.enterprise_default_tenant_id, settings.enterprise_default_user_id
        with closing(sqlite3.connect(settings.manufacturing_database_path)) as connection:
            cls.lots = [row[0] for row in connection.execute("SELECT DISTINCT lot_id FROM process_runs ORDER BY lot_id LIMIT 5")]

    def body(self):
        return {
            "groups": [
                {"group_id": "main", "name": "本次异常", "role": "primary", "lot_ids": self.lots[:3]},
                {"group_id": "ref", "name": "正常参考", "role": "normal_reference", "lot_ids": self.lots[3:]},
            ],
            "dimensions": ["equipment", "chamber", "path_adjacent"],
            "scope": {"time_range": None, "cutoff": None},
            "timezone": "Asia/Shanghai",
        }

    def test_real_source_and_session_bound_tool_results(self):
        page = self.client.post(BASE, json=self.body())
        self.assertEqual(page.status_code, 200, page.text)
        summary = page.json()
        self.assertEqual(summary["source"]["kind"], "sqlite")
        self.assertTrue(summary["candidates"])
        self.assertEqual(
            datetime.fromisoformat(summary["expires_at"]) - datetime.fromisoformat(summary["created_at"]),
            timedelta(days=7),
        )
        session = self.client.post("/api/sessions").json()
        session_id = session.get("session_id") or session["id"]
        tools = _tools(lot_commonality_service(), self.tenant, session_id=session_id)
        created = _call(tools, _Principal(self.tenant, self.user), CREATE_TOOL, self.body())
        self.assertIs(created.status, ToolStatus.SUCCEEDED, created.error)
        tool_ref = created.data["analysis_ref"]
        self.assertIsNone(created.data["expires_at"])
        candidate = created.data["candidates"][0]["candidate_id"]
        query = {"group_id": "main", "conditions": [{"candidate_id": candidate}]}
        via_tool = _call(tools, _Principal(self.tenant, self.user), MEMBERS_TOOL, {"analysis_ref": tool_ref, **query})
        via_http = self.client.post(f"{BASE}/{tool_ref}/members", json=query).json()
        self.assertEqual(via_tool.data, via_http)

        deleted = self.client.delete(f"/api/sessions/{session_id}/permanent")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        gone = self.client.get(f"{BASE}/{tool_ref}")
        self.assertEqual((gone.status_code, gone.json()["error_code"]), (404, "RESULT_UNAVAILABLE"))
        after = _call(tools, _Principal(self.tenant, self.user), CREATE_TOOL, self.body())
        self.assertEqual(after.error.code, "RESULT_UNAVAILABLE")
        self.assertEqual(self.client.get(f"{BASE}/{summary['analysis_ref']}").status_code, 200)

    def test_other_tenant_is_denied_by_the_source(self):
        response = self.client.post(BASE, json=self.body(), headers={"x-tenant-id": "tenant-b", "x-user-id": "engineer"})
        self.assertEqual((response.status_code, response.json()["error_code"]), (403, "SCOPE_DENIED"))

    def test_default_tool_catalog_does_not_include_the_optional_tools(self):
        names = {definition.name for definition in BUSINESS_TOOL_DEFINITIONS}
        self.assertEqual(len(names), 21)
        self.assertFalse(names & set(LOT_COMMONALITY_DEFINITIONS))


if __name__ == "__main__":
    unittest.main()
