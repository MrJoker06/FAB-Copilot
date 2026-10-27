from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKER = PROJECT_DIR / "scripts" / "modularization_paired_baseline.py"

FAKE_FIXTURE = """import app
import os
import time
async def _capture_ready():
    start = time.perf_counter_ns()
    end = time.perf_counter_ns()
    return {"elapsed_runtime_ns": end - start or 1}
async def _capture_loop(*, duplicate=False, knowledge=False):
    return await _capture_ready()
def collect_behavior():
    forbidden = {"FAB_TOKEN", "DEEPSEEK_KEY", "AGENT_LOG_PATH", "DB_HOST", "DATABASE_URL", "PYTHONPATH", "API_TIMEOUT_MS"}
    return {"secret_present": bool(forbidden & set(os.environ)), "env_files": [os.environ.get("FAB_WORKSPACE_ENV_FILE"), os.environ.get("FAB_PROJECT_ENV_FILE")]}
"""

ONE_TIMER_FIXTURE = FAKE_FIXTURE.replace(
    '    end = time.perf_counter_ns()\n    return {"elapsed_runtime_ns": end - start or 1}',
    '    return {"elapsed_runtime_ns": start or 1}',
)


def write_fake_app(root: Path) -> None:
    for package in ("agent_runtime", "intent_runtime"):
        directory = root / "app" / package
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "agent_runtime" / "service.py").write_text(
        'SYSTEM_PROMPT = "当前日期是 2099-01-01。用户说：fake"\n', encoding="utf-8"
    )
    (root / "app" / "intent_runtime" / "routing.py").write_text(
        "from datetime import date\n", encoding="utf-8"
    )


class PairedWorkerTests(unittest.TestCase):
    def test_cpu_stamps_use_the_two_fixture_boundaries(self):
        spec = importlib.util.spec_from_file_location("paired_timing_test", WORKER)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        fixture = SimpleNamespace()

        async def capture(**_kwargs):
            started = fixture.time.perf_counter_ns()
            return {"elapsed_runtime_ns": fixture.time.perf_counter_ns() - started}

        fixture._capture_ready = fixture._capture_loop = capture
        stream = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(module, "_worker_module", return_value=fixture),
            patch.object(module, "_origins", return_value={"app": ["/tmp/app.py"]}),
            patch.object(module, "_CLOCK", side_effect=[100, 120, 1000, 1100]),
            patch.object(
                module._stdlib_time, "thread_time_ns", side_effect=[200, 240]
            ) as thread,
            patch.object(
                module._stdlib_time, "process_time_ns", side_effect=[500, 560]
            ) as process,
            patch.object(
                sys,
                "stdin",
                io.StringIO(
                    '{"command":"measure","scene":"ready_success","count":1}\n{"command":"quit"}\n'
                ),
            ),
            patch.object(sys, "stdout", stream),
        ):
            self.assertEqual(0, module.worker_main(Path("/tmp")))
        result = json.loads(stream.getvalue().splitlines()[0])
        self.assertEqual([100], result["wall_samples_ns"])
        self.assertEqual([40], result["thread_cpu_samples_ns"])
        self.assertEqual([60], result["process_cpu_samples_ns"])
        self.assertEqual([20], result["cleanup_samples_ns"])
        self.assertEqual(2, thread.call_count)
        self.assertEqual(2, process.call_count)

    def test_worker_sanitizes_environment_and_has_prepare_measure_shapes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "app").mkdir()
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            write_fake_app(root)
            (root / "scripts" / "modularization_baseline.py").write_text(
                FAKE_FIXTURE, encoding="utf-8"
            )
            env = os.environ | {
                "FAB_TOKEN": "x",
                "DEEPSEEK_KEY": "x",
                "API_TIMEOUT_MS": "1",
                "AGENT_LOG_PATH": "x",
                "DATABASE_URL": "x",
                "PYTHONPATH": "x",
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(WORKER),
                    "--worker",
                    "--project-dir",
                    str(root),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                env=env,
            )
            assert process.stdin and process.stdout

            def command(payload):
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
                return json.loads(process.stdout.readline())

            try:
                ready = command({"command": "ready"})
                self.assertIn("environment", ready)
                self.assertTrue(ready["origins"])
                self.assertTrue(
                    all(
                        Path(path).is_relative_to(root)
                        for paths in ready["origins"].values()
                        for path in paths
                    )
                )
                self.assertEqual(
                    {
                        "network_calls": 0,
                        "database_calls": 0,
                        "env_files": {
                            "workspace": os.devnull,
                            "project": os.devnull,
                        },
                    },
                    ready["offline_policy"],
                )
                behavior = command({"command": "behavior"})["behavior"]
                self.assertFalse(behavior["secret_present"])
                self.assertEqual([os.devnull, os.devnull], behavior["env_files"])
                prepared = command({"command": "prepare", "scene": "ready_success"})
                self.assertEqual(1, len(prepared["first_run_ns"]))
                self.assertEqual(10, len(prepared["warmups_ns"]))
                self.assertEqual(11, len(prepared["cleanup_samples_ns"]))
                measured = command(
                    {"command": "measure", "scene": "loop_success", "count": 2}
                )
                for key in (
                    "wall_samples_ns",
                    "thread_cpu_samples_ns",
                    "process_cpu_samples_ns",
                    "cleanup_samples_ns",
                    "collected_objects",
                ):
                    self.assertEqual(2, len(measured[key]))
                self.assertEqual(0, measured["offline_policy"]["network_calls"])
                self.assertEqual(0, measured["offline_policy"]["database_calls"])
                self.assertTrue(command({"command": "quit"})["quit"])
                self.assertEqual(0, process.wait(timeout=10))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                process.stdin.close()
                process.stdout.close()

    def test_worker_rejects_fixture_with_not_exactly_two_timer_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "app").mkdir()
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            write_fake_app(root)
            (root / "scripts" / "modularization_baseline.py").write_text(
                ONE_TIMER_FIXTURE, encoding="utf-8"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(WORKER),
                    "--worker",
                    "--project-dir",
                    str(root),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdin
            try:
                process.stdin.write(
                    json.dumps(
                        {"command": "measure", "scene": "ready_success", "count": 1}
                    )
                    + "\n"
                )
                process.stdin.flush()
                self.assertNotEqual(0, process.wait(timeout=10))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                assert process.stdin and process.stdout and process.stderr
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()

    def test_origins_reject_a_loaded_app_module_outside_project(self):
        external = SimpleNamespace(
            __file__=str(Path(tempfile.gettempdir()) / "outside.py")
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(sys.modules, {"app.external_origin": external}),
            self.assertRaisesRegex(RuntimeError, "mixed import origin"),
        ):
            spec = importlib.util.spec_from_file_location("paired_worker", WORKER)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            module._origins(Path(temporary))
