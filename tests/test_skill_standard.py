"""Standard Skill packages, evidence-policy states and protocol tool views."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.tools.contracts import (
    ToolError,
    ToolErrorKind,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
)
from app.agent_runtime.tools.projection import (
    mcp_call_result,
    mcp_tool_view,
    model_function_view,
)
from app.bootstrap.litho_cpk_demo import _QUESTION, _TOOLS, _bindings, _Principal
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.skill_assembly import (
    EVIDENCE_CHECK_FAILED,
    EVIDENCE_CHECKED,
    SkillAssemblyConfiguration,
    SkillAssemblyError,
    SkillExecutionRequest,
    resolve_skill_binding,
)
from app.intent_runtime.routing import route_question
from app.tools.process_diagnostics.binding import PROCESS_CAPABILITY_DEFINITION
from app.skills.contracts import ComponentReference as SkillComponentReference
from app.skills.contracts import SkillPackageError
from app.skills.frontmatter import parse_skill_document
from app.skills.manifest import parse_manifest
from app.skills.standard import (
    EXECUTION_EXTENSION,
    NO_EXECUTION_EXTENSION,
    inspect_skill,
)
from app.tools.capability_trend.tool import CAPABILITY_TREND_DEFINITION

ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = ROOT / "app" / "skills" / "litho-cpk-diagnostic"
AS_OF = date(2026, 10, 31)
VALID = "---\nname: demo-skill\ndescription: Demo instructions.\n---\n# Body\n"


class FrontmatterTests(unittest.TestCase):
    def test_standard_fields_metadata_and_body_are_parsed(self) -> None:
        document = parse_skill_document(
            "---\n"
            "name: demo-skill\n"
            'description: "Use it: carefully"\n'
            "license: Apache-2.0\n"
            "metadata:\n"
            "  domain: litho\n"
            "  owner: 'fab team'\n"
            "---\n\n# Steps\n\nDo it.\n"
        )
        self.assertEqual(document.name, "demo-skill")
        self.assertEqual(document.description, "Use it: carefully")
        self.assertEqual(document.license, "Apache-2.0")
        self.assertEqual(dict(document.metadata), {"domain": "litho", "owner": "fab team"})
        self.assertEqual(document.body, "# Steps\n\nDo it.")

    def test_unsupported_or_ambiguous_documents_are_rejected(self) -> None:
        for text in (
            "# no frontmatter\n",
            "---\nname: demo-skill\ndescription: x\n",
            "---\nname: Demo_Skill\ndescription: x\n---\n",
            "---\nname: demo-skill\n---\n",
            "---\nname: demo-skill\ndescription: x\nversion: 1\n---\n",
            "---\nname: demo-skill\ndescription: true\n---\n",
            "---\nname: demo-skill\ndescription: a: b\n---\n",
            "---\nname: demo-skill\nname: other\ndescription: x\n---\n",
            "---\nname: demo-skill\ndescription: x\nmetadata: inline\n---\n",
            "---\nname: demo-skill\n\tdescription: x\n---\n",
            "---\nname: demo-skill\ndescription: [x]\n---\n",
        ):
            with self.subTest(text=text), self.assertRaises(SkillPackageError) as caught:
                parse_skill_document(text)
            self.assertEqual(caught.exception.code, "invalid_skill_document")


class StandardPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.parent = Path(directory.name)

    def _package(self, name: str, text: str = VALID) -> Path:
        root = self.parent / name
        root.mkdir()
        (root / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")
        return root

    def test_minimal_package_needs_only_skill_md_and_grants_no_execution(self) -> None:
        skill = inspect_skill(self._package("demo-skill"))
        self.assertIsNone(skill.manifest)
        self.assertEqual(skill.execution_status, NO_EXECUTION_EXTENSION)
        self.assertFalse(skill.execution_authorized)
        self.assertEqual(skill.instructions, "# Body")

    def test_name_must_match_directory(self) -> None:
        with self.assertRaises(SkillPackageError) as caught:
            inspect_skill(self._package("other-name"))
        self.assertEqual(caught.exception.code, "invalid_skill_document")

    def test_pilot_package_is_standard_with_execution_extension(self) -> None:
        skill = inspect_skill(SKILL_SOURCE)
        self.assertEqual(skill.document.name, "litho-cpk-diagnostic")
        self.assertEqual(skill.execution_status, EXECUTION_EXTENSION)
        self.assertFalse(skill.execution_authorized)
        self.assertEqual(skill.manifest.version, "2.0.0")
        self.assertEqual(skill.manifest.description, skill.document.description)

    def test_v2_manifest_takes_identity_from_skill_md(self) -> None:
        document = parse_skill_document(VALID)
        manifest = parse_manifest(
            json.dumps(
                {"schema_version": "2.0.0", "version": "0.1.0", "status": "draft"}
            ),
            document=document,
        )
        self.assertEqual(manifest.skill_id, "demo-skill")
        self.assertEqual(manifest.title, "demo-skill")
        self.assertIsNone(manifest.workflow)
        self.assertIsNone(manifest.evidence_policy)
        self.assertEqual(
            [item.path for item in manifest.resources], ["SKILL.md"]
        )

    def test_v2_manifest_rejects_missing_document_unknown_fields_and_bad_policy(
        self,
    ) -> None:
        document = parse_skill_document(VALID)
        base = {"schema_version": "2.0.0", "version": "0.1.0", "status": "draft"}
        cases = (
            (base, None, "invalid_manifest"),
            ({**base, "skill_id": "demo-skill"}, document, "invalid_manifest"),
            ({**base, "evidence_policy": "capability-evidence"}, document,
             "invalid_evidence_policy"),
            ({**base, "evidence_policy": {"component_id": "x"}}, document,
             "invalid_evidence_policy"),
        )
        for value, candidate, code in cases:
            with self.subTest(value=value), self.assertRaises(SkillPackageError) as caught:
                parse_manifest(json.dumps(value), document=candidate)
            self.assertEqual(caught.exception.code, code)


class EvidencePolicyStateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "litho-cpk-diagnostic"
        shutil.copytree(SKILL_SOURCE, self.root)

    def _resolve(self, *, skill_version="2.0.0", workflows=None, release_store=None):
        route = route_question(_QUESTION, AS_OF)
        workflow = LithoCpkWorkflow()
        plan, _ = workflow.build(_QUESTION, route)
        bindings, adapters = _bindings(plan, AS_OF, _Principal())
        self.adapters = adapters
        definition = AgentDefinition(
            "evidence-test",
            "1.0.0",
            "analyst",
            "controlled test",
            tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
            ComponentReference("model", "1.0.0"),
            ComponentReference("policy", "1.0.0"),
            (ComponentReference("litho-cpk-diagnostic", skill_version),),
        )
        binding = resolve_skill_binding(
            definition,
            SkillAssemblyConfiguration(
                (self.root,) if release_store is None else (),
                workflows or (workflow,), release_store,
            ),
            SkillExecutionRequest(_QUESTION, route, "ready"),
            bindings,
            frozenset(_TOOLS),
        )
        return binding, adapters

    def _edit_manifest(self, change) -> None:
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        change(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_undeclared_policy_cannot_bypass_controlled_diagnosis(self) -> None:
        self._edit_manifest(lambda value: value.pop("evidence_policy"))
        with self.assertRaises(SkillAssemblyError) as caught:
            self._resolve()
        self.assertEqual(caught.exception.reason, "required_policy_missing")
        self.assertTrue(all(not adapter.calls for adapter in self.adapters))

    def test_released_old_and_current_policy_versions_resolve_without_latest_binding(self):
        from app.bootstrap.skill_assembly import _inventory
        from app.skills.catalog import SkillReference
        from app.skills.releases import SkillReleaseStore

        current_document = (self.root / "manifest.json").read_text(encoding="utf-8")
        workflow = LithoCpkWorkflow()
        old_workflow = LithoCpkWorkflow(version="2.1.0", evidence_policy_version="1.3.0")
        route = route_question(_QUESTION, AS_OF)
        plan, _ = workflow.build(_QUESTION, route)
        bindings, _ = _bindings(plan, AS_OF, _Principal())
        store = SkillReleaseStore()
        old = json.loads(current_document)
        old["version"] = "1.1.0"
        old["workflow"]["version"] = "2.1.0"
        old["evidence_policy"]["version"] = "1.3.0"
        (self.root / "manifest.json").write_text(json.dumps(old), encoding="utf-8")
        store.publish(self.root, _inventory(bindings, (old_workflow,)))
        store.activate(SkillReference("litho-cpk-diagnostic", "1.1.0"))
        (self.root / "manifest.json").write_text(current_document, encoding="utf-8")
        store.publish(self.root, _inventory(bindings, (workflow,)))
        store.activate(SkillReference("litho-cpk-diagnostic", "2.0.0"))
        for ordered in ((old_workflow, workflow), (workflow, old_workflow)):
            for skill_version, expected in (("1.1.0", "1.3.0"), ("2.0.0", "2.0.0")):
                with self.subTest(order=ordered, version=skill_version):
                    binding, _ = self._resolve(skill_version=skill_version, workflows=ordered, release_store=store)
                    report = binding.check_evidence([])
                    self.assertEqual(report.status, EVIDENCE_CHECKED)
                    self.assertEqual(report.validation.validator_version, expected)
                    self.assertEqual(report.validation.policy_ref["version"], expected)
        store.rollback(SkillReference("litho-cpk-diagnostic", "1.1.0"))
        binding, _ = self._resolve(skill_version="1.1.0", workflows=(workflow, old_workflow), release_store=store)
        self.assertEqual(binding.check_evidence([]).validation.validator_version, "1.3.0")

    def test_unparseable_declared_policy_fails_assembly_before_fetch(self) -> None:
        for value in ("capability-evidence", {"component_id": "capability-evidence"}):
            with self.subTest(value=value):
                self._edit_manifest(lambda item: item.update(evidence_policy=value))
                with self.assertRaises(SkillAssemblyError) as caught:
                    self._resolve()
                self.assertEqual(caught.exception.reason, "invalid_evidence_policy")

    def test_unresolvable_declared_policy_fails_assembly(self) -> None:
        self._edit_manifest(
            lambda item: item.update(
                evidence_policy={"component_id": "capability-evidence", "version": "9.0.0"}
            )
        )
        with self.assertRaises(SkillAssemblyError) as caught:
            self._resolve()
        self.assertEqual(caught.exception.reason, "incompatible_dependency")

    def test_declared_policy_runs_and_reports_insufficient_evidence(self) -> None:
        binding, _ = self._resolve()
        self.assertEqual(dict(binding.metadata)["evidence_policy_status"], "configured")
        outcome = binding.check_evidence([])
        self.assertEqual(outcome.status, EVIDENCE_CHECKED)
        self.assertEqual(
            outcome.policy, SkillComponentReference("capability-evidence", "2.0.0")
        )
        self.assertIsNotNone(outcome.validation)
        self.assertIs(outcome.evidence_sufficient, False)

    def test_sufficiency_follows_validation_and_check_failure_is_distinct(self) -> None:
        binding, _ = self._resolve()

        def stub(result=None, error=None):
            def validator(*_args):
                if error is not None:
                    raise error
                return result

            return replace(
                binding, workflow=SimpleNamespace(evidence_validator=validator)
            )

        cases = (
            (SimpleNamespace(status="validated", allowed_conclusion_strength="strong"),
             EVIDENCE_CHECK_FAILED, None),
            (SimpleNamespace(status="validated", allowed_conclusion_strength="insufficient"),
             EVIDENCE_CHECK_FAILED, None),
            (SimpleNamespace(status="rejected", allowed_conclusion_strength="strong"),
             EVIDENCE_CHECK_FAILED, None),
        )
        for validation, status, sufficient in cases:
            with self.subTest(validation=validation):
                outcome = stub(validation).check_evidence([])
                self.assertEqual(outcome.status, status)
                self.assertIs(outcome.evidence_sufficient, sufficient)
        failed = stub(error=RuntimeError("validator exploded")).check_evidence([])
        self.assertEqual(failed.status, EVIDENCE_CHECK_FAILED)
        self.assertEqual(failed.validation.assessment_reason, "checker_unavailable")
        self.assertIsNone(failed.evidence_sufficient)


class ProjectionTests(unittest.TestCase):
    def test_model_view_keeps_the_legacy_function_shape(self) -> None:
        for definition in (PROCESS_CAPABILITY_DEFINITION, CAPABILITY_TREND_DEFINITION):
            with self.subTest(tool=definition.name):
                view = model_function_view(definition)
                self.assertEqual(set(view), {"type", "function"})
                self.assertEqual(
                    set(view["function"]), {"name", "description", "parameters"}
                )
                self.assertEqual(view["function"]["parameters"], definition.json_schema())

    def test_mcp_view_carries_title_schemas_and_read_only_hint(self) -> None:
        view = mcp_tool_view(CAPABILITY_TREND_DEFINITION)
        self.assertEqual(view["name"], "get_capability_trend")
        self.assertEqual(view["title"], "制程能力周趋势")
        self.assertEqual(view["inputSchema"], CAPABILITY_TREND_DEFINITION.json_schema())
        self.assertEqual(view["annotations"], {"readOnlyHint": True})
        self.assertEqual(view["outputSchema"]["type"], "object")
        self.assertEqual(view["outputSchema"]["required"], ["rows"])
        view["inputSchema"]["properties"] = {}
        self.assertNotEqual(
            CAPABILITY_TREND_DEFINITION.json_schema()["properties"], {}
        )

    def test_call_result_maps_success_and_failure_without_raising(self) -> None:
        rows = [
            {
                "week_start": "2026-10-05",
                "period_start": "2026-10-05",
                "period_end": "2026-10-08",
                "process_step": "LITHO",
                "equipment_id": "LITHO-01",
                "samples": 3,
                "mean_value": 11.0,
                "sigma": 1.633,
                "cpk": 0.2,
                "metric_name": "cd",
                "metric_unit": "nm",
                "spec_lsl": 9.0,
                "spec_usl": 12.0,
            }
        ]
        ok = mcp_call_result(
            ToolResult(
                "c1", "get_capability_trend", "1.0.0", ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED, data=rows,
            )
        )
        self.assertFalse(ok["isError"])
        self.assertEqual(ok["structuredContent"], {"rows": rows})
        self.assertEqual(json.loads(ok["content"][0]["text"]), {"rows": rows})
        jsonschema.validate(
            ok["structuredContent"],
            mcp_tool_view(CAPABILITY_TREND_DEFINITION)["outputSchema"],
        )
        failed = mcp_call_result(
            ToolResult(
                "c2", "get_capability_trend", "1.0.0", ToolStatus.FAILED,
                ToolExecutionState.COMPLETED,
                error=ToolError("source_unavailable", "数据源不可用", ToolErrorKind.DATA_SOURCE),
            )
        )
        self.assertTrue(failed["isError"])
        self.assertNotIn("structuredContent", failed)
        self.assertEqual(failed["content"][0]["text"], "source_unavailable: 数据源不可用")
        with self.assertRaises(TypeError):
            mcp_call_result({"status": "succeeded"})


if __name__ == "__main__":
    unittest.main()
