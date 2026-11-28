import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.tools.contracts import ToolStatus
from app.bootstrap import capability_catalog as catalog
from app.bootstrap.default_tool_assembly import build_default_run_tools
from app.core.identity import Principal
from app.main import app
from tests.test_capability_trend_tool import _write_database
from tests.test_default_tool_assembly import _plan


class CapabilityDirectoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.addCleanup(patch.stopall)
        patch.object(catalog, "db_path", return_value=root / "directory.db").start()
        patch.dict(
            os.environ,
            {"FAB_ADMIN_API_TOKEN": "fixture-token", "FAB_REQUIRE_IDENTITY": "false"},
        ).start()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.admin = {"Authorization": "Bearer fixture-token"}
        self.member = Principal("demo", "member", modules=("质量",))

    def register(self, kind, name, *, access=None, enabled=True):
        response = self.client.put(
            f"/api/admin/capabilities/{kind}/{name}",
            headers=self.admin,
            json={"access": access, "enabled": enabled, "groups": ["值班排查"]},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_directory_uses_platform_identity_independently_of_personal_upload_token(
        self,
    ):
        with patch.dict(
            os.environ,
            {
                "FAB_PERSONAL_KNOWLEDGE_API_TOKEN": "upload-fixture",
                "FAB_REQUIRE_IDENTITY": "true",
            },
        ):
            self.assertEqual(self.client.get("/api/capabilities").status_code, 401)
            response = self.client.get(
                "/api/capabilities",
                headers={"X-Tenant-ID": "demo", "X-User-ID": "member"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["items"]), 21)

    def test_skill_registration_scope_and_missing_tool(self):
        name = "litho-cpk-diagnostic"
        self.assertEqual(
            self.client.get(
                "/api/admin/capabilities", headers={"X-Roles": "admin"}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.put(
                "/api/admin/capabilities/skill/" + name,
                json={"access": None, "enabled": True},
            ).status_code,
            401,
        )
        self.register("skill", name, access={"owner": "Litho", "readers": ["质量"]})
        public = self.client.get("/api/capabilities", headers={"X-Modules": "Litho"})
        self.assertEqual(public.status_code, 200)
        self.assertNotIn(name, public.text)
        skill = next(x for x in catalog.directory(self.member) if x["name"] == name)
        self.assertFalse(skill["dependencies_ready"])
        self.assertNotIn("instructions", skill)
        self.register("tool", "get_capability_trend", access={"owner": "Etch"})
        skill = next(x for x in catalog.directory(self.member) if x["name"] == name)
        self.assertNotIn("instructions", skill)
        self.assertNotIn("get_capability_trend", json.dumps(skill))
        self.register("tool", "get_capability_trend")
        skill = next(x for x in catalog.directory(self.member) if x["name"] == name)
        self.assertTrue(skill["dependencies_ready"])
        self.assertIn("instructions", skill)
        self.register("skill", name, enabled=False)
        self.assertNotIn(name, [x["name"] for x in catalog.directory(self.member)])

    def test_invalid_skill_is_reported_separately_and_cannot_be_enabled(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, {"FAB_SKILLS_ROOT": raw}),
        ):
            root = Path(raw) / "broken"
            root.mkdir()
            (root / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
            admin = self.client.get(
                "/api/admin/capabilities", headers=self.admin
            ).json()["items"]
            self.assertTrue(
                next(row for row in admin if row["name"] == "broken")[
                    "availability_issue"
                ]
            )
            self.assertEqual(
                self.client.put(
                    "/api/admin/capabilities/skill/broken",
                    headers=self.admin,
                    json={"access": None, "enabled": True},
                ).status_code,
                409,
            )
            visible = self.client.get("/api/capabilities").json()["items"]
            self.assertEqual(len(visible), 21)
            self.assertNotIn("broken", [item["name"] for item in visible])

    def test_tool_filter_and_inflight_revocation(self):
        plan = replace(
            _plan("get_capability_trend"), route_intent="capability_excursion"
        )

        database = catalog.db_path().with_name("manufacturing.db")
        _write_database(database)

        def assemble():
            return build_default_run_tools(
                settings=SimpleNamespace(
                    manufacturing_database_path=database,
                    enterprise_default_tenant_id="demo",
                ),
                principal=self.member,
                plan=plan,
                guard=ToolLoopGuard(plan),
                run_id="directory",
                usable_knowledge_result=lambda *_: True,
                management=catalog,
            )

        tool = "get_capability_trend"
        self.assertNotIn(tool, assemble().dispatcher.allowed_tools)
        self.register("tool", tool, access={"owner": "质量"})
        run = assemble()
        self.assertIn(
            tool, [t["function"]["name"] for t in json.loads(run.loop.tools_json)]
        )
        fresh = assemble()
        success = asyncio.run(
            fresh.dispatcher.dispatch(
                tool,
                '{"start":"2026-10-01","end":"2026-10-08","process_step":"LITHO"}',
                fresh.context.for_tool_call("read"),
            )
        )
        self.assertEqual(success.status, ToolStatus.SUCCEEDED, success)
        self.assertIn("LITHO-01", {row["equipment_id"] for row in success.data})
        self.register("tool", tool, enabled=False)
        result = asyncio.run(
            run.dispatcher.dispatch(tool, "{}", run.context.for_tool_call("revoked"))
        )
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertNotIn(tool, assemble().dispatcher.allowed_tools)
