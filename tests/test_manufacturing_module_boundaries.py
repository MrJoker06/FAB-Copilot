from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.manufacturing import enterprise_data, playbooks, processes, reports, seed
from app.agent_runtime.tools import registry
from scripts.check_module_boundaries import boundary_errors, load_manifest


class ManufacturingModuleBoundaryTests(unittest.TestCase):
    def test_canonical_exports_have_domain_owners_and_tool_wiring(self):
        root = Path(__file__).resolve().parents[1] / "app"
        for name in ("processes", "domain_playbooks", "reports", "enterprise_data", "seed"):
            self.assertFalse((root / f"{name}.py").exists())
        owners = (
            (processes.matched_process_step, "app.manufacturing.processes"),
            (playbooks.DomainPlaybook, "app.manufacturing.playbooks"),
            (playbooks.select_playbook, "app.manufacturing.playbooks"),
            (reports.report_bundle, "app.manufacturing.reports"),
            (enterprise_data.EnterpriseDataError, "app.manufacturing.enterprise_data"),
            (enterprise_data.get_enterprise_provider, "app.manufacturing.enterprise_data"),
            (seed.generate_database, "app.manufacturing.seed"),
        )
        for value, owner in owners:
            self.assertEqual(value.__module__, owner)
        self.assertIs(registry.TOOL_HANDLERS["query_enterprise_data"], enterprise_data.query_enterprise_data)
        self.assertIs(registry.TOOL_HANDLERS["get_fab_overview"], reports.fab_overview)

    def test_seed_main_restores_live_patch_dependencies(self):
        generated = {"generated": True}
        with (
            patch.object(seed, "ensure_department_databases") as ensure,
            patch.object(seed, "db_session") as session,
            patch.object(seed, "generate_database", return_value=generated) as generate,
        ):
            session.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
            self.assertEqual(seed.main(["--days", "1", "--end-date", "2026-12-25"]), 0)
        ensure.assert_called_once_with()
        generate.assert_called_once_with(days=1, end_date=seed._parse_end_date("2026-12-25"))
        self.assertIsNot(seed.db_session, session)

    def test_seed_main_skips_existing_data_without_force(self):
        with (
            patch.object(seed, "ensure_department_databases") as ensure,
            patch.object(seed, "db_session") as session,
            patch.object(seed, "generate_database") as generate,
        ):
            session.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (True,)
            self.assertEqual(seed.main(["--days", "1", "--end-date", "2026-12-25"]), 0)
        ensure.assert_called_once_with()
        generate.assert_not_called()

    def test_seed_cli_rejects_invalid_date_before_database_access(self):
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
