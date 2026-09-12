from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import answer_synthesizer, evidence_semantics, evidence_validator, knowledge_decision, ocr, ocr_quality, rag
from app.agent_runtime.tools import catalog, registry
from app.evidence import answer_synthesizer as canonical_answer
from app.evidence import semantics, validator
from app.knowledge import decision, ocr as canonical_ocr, ocr_quality as canonical_quality, rag as canonical_rag
from scripts.check_module_boundaries import boundary_errors, load_manifest


class KnowledgeEvidenceModuleBoundaryTests(unittest.TestCase):
    def test_legacy_facades_retain_canonical_public_and_private_identity(self):
        self.assertIs(rag.search_knowledge, canonical_rag.search_knowledge)
        self.assertIs(rag.PROCESS_STEPS, canonical_rag.PROCESS_STEPS)
        self.assertIs(knowledge_decision.RetrievalDecision, decision.RetrievalDecision)
        self.assertIs(knowledge_decision.required_scopes, decision.required_scopes)
        self.assertIs(ocr.OCRResult, canonical_ocr.OCRResult)
        self.assertIs(ocr.OCRUnavailableError, canonical_ocr.OCRUnavailableError)
        self.assertIs(ocr._engine_lock, canonical_ocr._engine_lock)
        self.assertIs(ocr._inference_lock, canonical_ocr._inference_lock)
        self.assertIs(ocr._engine, canonical_ocr._engine)
        self.assertIs(ocr_quality.OCRObservation, canonical_quality.OCRObservation)
        self.assertIs(evidence_semantics.EvidenceScope, semantics.EvidenceScope)
        self.assertIs(evidence_validator.EvidenceObservation, validator.EvidenceObservation)
        self.assertIs(answer_synthesizer.AnswerContract, canonical_answer.AnswerContract)
        self.assertIs(answer_synthesizer.SUBMIT_ANALYSIS_TOOL, canonical_answer.SUBMIT_ANALYSIS_TOOL)

    def test_catalog_and_registered_handlers_use_canonical_objects(self):
        self.assertIs(registry.TOOL_HANDLERS["search_knowledge"], canonical_rag.search_agent_knowledge)
        self.assertIs(catalog.SUBMIT_ANALYSIS_TOOL, canonical_answer.SUBMIT_ANALYSIS_TOOL)
        self.assertIn(canonical_answer.SUBMIT_ANALYSIS_TOOL, catalog.TOOLS)

    def test_ocr_cache_and_locks_are_shared_without_engine_construction(self):
        original_engine = canonical_ocr._engine
        sentinel = object()
        with patch.object(canonical_ocr, "_engine", sentinel):
            self.assertIs(ocr.get_ocr_engine(), sentinel)
            self.assertIs(canonical_ocr.get_ocr_engine(), sentinel)
            self.assertIs(ocr._engine, sentinel)
        self.assertIs(canonical_ocr._engine, original_engine)
        self.assertIs(ocr._engine, original_engine)

    def test_import_orders_do_not_eagerly_construct_ocr_engine_or_cycle(self):
        guard = (
            "import socket; socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
            "import httpx; httpx.Client.send = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
            "httpx.AsyncClient.send = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network')); "
        )
        orders = (
            guard + "import app.rag; import app.knowledge_decision; import app.ocr; import app.ocr_quality; import app.evidence_semantics; import app.evidence_validator; import app.answer_synthesizer; import app.personal_knowledge; import app.knowledge.ocr as value; print(value._engine is None)",
            guard + "import app.knowledge.rag; import app.knowledge.decision; import app.knowledge.ocr as value; import app.knowledge.ocr_quality; import app.evidence.semantics; import app.evidence.validator; import app.evidence.answer_synthesizer; import app.personal_knowledge; import app.ocr; import app.ocr_quality; import app.rag; import app.knowledge_decision; import app.evidence_semantics; import app.evidence_validator; import app.answer_synthesizer; print(value._engine is None)",
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
