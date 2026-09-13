from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.evidence import answer_synthesizer, semantics as evidence_semantics, validator as evidence_validator
from app.knowledge import decision as knowledge_decision, ocr, ocr_quality, rag
from app.agent_runtime.tools import catalog, registry
from scripts.check_module_boundaries import boundary_errors, load_manifest


class KnowledgeEvidenceModuleBoundaryTests(unittest.TestCase):
    def test_canonical_exports_have_domain_owners_and_removed_roots(self):
        root = Path(__file__).resolve().parents[1] / "app"
        for name in ("rag", "knowledge_decision", "ocr", "ocr_quality", "evidence_semantics", "evidence_validator", "answer_synthesizer"):
            self.assertFalse((root / f"{name}.py").exists())
        owners = (
            (rag.search_knowledge, "app.knowledge.rag"), (knowledge_decision.RetrievalDecision, "app.knowledge.decision"),
            (knowledge_decision.required_scopes, "app.knowledge.decision"), (ocr.OCRResult, "app.knowledge.ocr"),
            (ocr.OCRUnavailableError, "app.knowledge.ocr"), (ocr_quality.OCRObservation, "app.knowledge.ocr_quality"),
            (evidence_semantics.EvidenceScope, "app.evidence.semantics"), (evidence_validator.EvidenceObservation, "app.evidence.validator"),
            (answer_synthesizer.AnswerContract, "app.evidence.answer_synthesizer"),
        )
        for value, owner in owners:
            self.assertEqual(value.__module__, owner)

    def test_catalog_and_registered_handlers_use_canonical_objects(self):
        self.assertIs(registry.TOOL_HANDLERS["search_knowledge"], rag.search_agent_knowledge)
        self.assertIs(catalog.SUBMIT_ANALYSIS_TOOL, answer_synthesizer.SUBMIT_ANALYSIS_TOOL)
        self.assertIn(answer_synthesizer.SUBMIT_ANALYSIS_TOOL, catalog.TOOLS)

    def test_ocr_cache_and_locks_are_shared_without_engine_construction(self):
        original_engine = ocr._engine
        sentinel = object()
        with patch.object(ocr, "_engine", sentinel):
            self.assertIs(ocr.get_ocr_engine(), sentinel)
            self.assertIs(ocr._engine, sentinel)
        self.assertIs(ocr._engine, original_engine)

    def test_import_orders_do_not_eagerly_construct_ocr_engine_or_cycle(self):
        guard = (
            "import socket; socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
            "import httpx; httpx.Client.send = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
            "httpx.AsyncClient.send = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
        )
        orders = (
            guard + "import app.knowledge.rag; import app.knowledge.decision; import app.knowledge.ocr; import app.knowledge.ocr_quality; import app.evidence.semantics; import app.evidence.validator; import app.evidence.answer_synthesizer; import app.personal_knowledge_runtime.service; import app.knowledge.ocr as value; print(value._engine is None)",
            guard + "import app.personal_knowledge_runtime.service; import app.evidence.answer_synthesizer; import app.evidence.validator; import app.evidence.semantics; import app.knowledge.ocr as value; import app.knowledge.ocr_quality; import app.knowledge.decision; import app.knowledge.rag; print(value._engine is None)",
        )
        for source in orders:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                environment = {**os.environ, "AGENT_LOG_PATH": f"{directory}/events.jsonl", "AGENT_RUN_LOG_DIR": f"{directory}/runs"}
                result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, check=False, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "True")

    def test_canonical_semantics_remains_a_pure_boundary_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            import shutil

            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "evidence" / "semantics.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nimport socket\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("app.evidence.semantics" in error and "pure module imports forbidden socket" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
