"""Fresh-environment acceptance tests for the delivery-only installer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_module_release.py"
spec = importlib.util.spec_from_file_location("verify_module_release", VERIFY)
assert spec and spec.loader
verify_module_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_module_release)


class ModuleReleaseInstallTests(unittest.TestCase):
    def test_delivery_copy_installs_real_tools_and_skill_in_isolated_venv(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            delivery = root / "delivery"
            # The builder itself is the normal release entrypoint.  Importing it
            # here avoids a checkout-derived installer in the acceptance phase.
            import sys

            sys.path.insert(0, str(ROOT / "scripts"))
            import module_release

            module_release.build(delivery, build_id="fresh-install-test")
            with self.assertRaisesRegex(ValueError, "outside delivery"):
                verify_module_release.verify(delivery, delivery / "recursive", None)
            self.assertFalse((delivery / "recursive").exists())
            report = verify_module_release.verify(delivery, root / "work", None)
            self.assertEqual(
                report["profiles"]["tool_sources+skill_release"]["status"],
                "PASS",
                report,
            )
            self.assertEqual(
                report["profiles"]["model_transport"]["status"], "NOTRUN", report
            )

    def test_model_transport_uses_explicit_offline_wheelhouse_when_available(
        self,
    ) -> None:
        wheelhouse = ROOT / "runtime" / "quality" / "mod-024-20261110-r1" / "wheelhouse"
        if not wheelhouse.is_dir():
            self.skipTest("MOD-024 offline wheelhouse is intentionally local evidence")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            import sys

            sys.path.insert(0, str(ROOT / "scripts"))
            import module_release

            delivery = root / "delivery"
            module_release.build(delivery, build_id="offline-model-test")
            report = verify_module_release.verify(delivery, root / "work", wheelhouse)
            self.assertEqual(
                report["profiles"]["model_transport"]["status"],
                "PASS",
                json.dumps(report, indent=2),
            )


if __name__ == "__main__":
    unittest.main()
