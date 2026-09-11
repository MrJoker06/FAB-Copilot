from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import domain_playbooks, enterprise_data, processes, reports, seed
from app.agent_runtime.tools import registry
from app.manufacturing import enterprise_data as canonical_enterprise_data
from app.manufacturing import playbooks, processes as canonical_processes, reports as canonical_reports
from app.manufacturing import seed as canonical_seed
from scripts.check_module_boundaries import boundary_errors, load_manifest


class ManufacturingModuleBoundaryTests(unittest.TestCase):
    def test_legacy_facades_retain_canonical_public_object_identity(self):
        self.assertIs(processes.MANUFACTURING_STEPS, canonical_processes.MANUFACTURING_STEPS)
        self.assertIs(processes.matched_process_step, canonical_processes.matched_process_step)
        self.assertIs(domain_playbooks.DOMAIN_PLAYBOOKS, playbooks.DOMAIN_PLAYBOOKS)
        self.assertIs(domain_playbooks.DomainPlaybook, playbooks.DomainPlaybook)
        self.assertIs(domain_playbooks.select_playbook, playbooks.select_playbook)
        self.assertIs(reports.report_bundle, canonical_reports.report_bundle)
        self.assertIs(enterprise_data.EnterpriseDataError, canonical_enterprise_data.EnterpriseDataError)
        self.assertIs(enterprise_data.get_enterprise_provider, canonical_enterprise_data.get_enterprise_provider)
        self.assertIs(seed.generate_database, canonical_seed.generate_database)
        self.assertIs(registry.TOOL_HANDLERS["query_enterprise_data"], canonical_enterprise_data.query_enterprise_data)
        self.assertIs(registry.TOOL_HANDLERS["get_fab_overview"], canonical_reports.fab_overview)

    def test_legacy_seed_main_forwards_live_patch_dependencies_without_mutating_canonical(self):
        generated = {"generated": True}
        with (
            patch.object(seed, "ensure_department_databases") as ensure,
            patch.object(seed, "db_session") as session,
            patch.object(seed, "generate_database", return_value=generated) as generate,
        ):
            session.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
            self.assertEqual(seed.main(["--days", "1", "--end-date", "2026-12-25"]), 0)
        ensure.assert_called_once_with()
        generate.assert_called_once_with(days=1, end_date=canonical_seed._parse_end_date("2026-12-25"))
        self.assertIsNot(canonical_seed.db_session, session)

    def test_canonical_seed_main_resolves_live_patch_dependencies(self):
        with (
            patch.object(canonical_seed, "ensure_department_databases") as ensure,
            patch.object(canonical_seed, "db_session") as session,
            patch.object(canonical_seed, "generate_database", return_value={"canonical": True}) as generate,
        ):
            session.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
            self.assertEqual(canonical_seed.main(["--days", "1", "--end-date", "2026-12-25"]), 0)
        ensure.assert_called_once_with()
        generate.assert_called_once_with(days=1, end_date=canonical_seed._parse_end_date("2026-12-25"))

    def test_legacy_seed_cli_rejects_invalid_date_before_database_access(self):
        with patch.object(seed, "ensure_department_databases") as ensure:
            with self.assertRaises(SystemExit):
                seed.main(["--end-date", "2026/12/25"])
        ensure.assert_not_called()

    def test_canonical_processes_is_a_pure_boundary_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            source = Path(__file__).resolve().parents[1] / "app"
            import shutil

            shutil.copytree(source, copied_app)
            target = copied_app / "manufacturing" / "processes.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nimport socket\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("app.manufacturing.processes" in error and "pure module imports forbidden socket" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
