from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import start_local_model as launcher

ROOT = Path(__file__).resolve().parents[1]

# Argument list of the original scripts/start-local-model.ps1 for its defaults
# (q4km, 80k, port 8080, text-only, MTP on, thinking off).
LEGACY_DEFAULT_ARGUMENTS = [
    "--host",
    "127.0.0.1",
    "--port",
    "8080",
    "--alias",
    "Qwen3.8-27B-Q4_K_M",
    "--gpu-layers",
    "all",
    "--ctx-size",
    "81920",
    "--parallel",
    "2",
    "--batch-size",
    "1024",
    "--ubatch-size",
    "256",
    "--cache-type-k",
    "q8_0",
    "--cache-type-v",
    "q8_0",
    "--flash-attn",
    "on",
    "--jinja",
    "--no-context-shift",
    "--fit",
    "off",
    "--spec-type",
    "draft-mtp",
    "--spec-draft-n-max",
    "2",
    "--reasoning",
    "off",
]

FAKE_SERVER = textwrap.dedent(
    """
    import json, os, sys, time
    from http.server import BaseHTTPRequestHandler, HTTPServer

    argv = sys.argv[1:]
    value = lambda flag: argv[argv.index(flag) + 1]
    mode = os.environ.get("FAKE_LLAMA_MODE", "serve")
    print("fake llama-server", " ".join(argv), flush=True)
    if mode == "exit":
        sys.exit(3)
    if mode == "hang":
        time.sleep(600)
        sys.exit(0)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": value("--alias")}]}).encode()
            self.send_response(200 if self.path == "/v1/models" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    HTTPServer((value("--host"), int(value("--port"))), Handler).serve_forever()
    """
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _touch(path: Path, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    if executable:
        path.chmod(0o755)
    return path


class StartLocalModelTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.deploy = self.root / "deploy"
        spec = launcher.MODELS["q4km"]
        self.model = _touch(self.deploy / "models" / spec.file)
        self.mmproj = self.deploy / "models" / spec.mmproj
        self.server = _touch(
            self.deploy / "runtimes" / "llama-cpp" / launcher.server_binary_name(),
            executable=True,
        )

    def _args(self, *extra: str):
        return launcher.parse_args(["--deployment-root", str(self.deploy), *extra])

    def _run(self, *extra: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = launcher.run(self._args(*extra), repo=self.repo)
            except launcher.LauncherError as error:
                print(f"error: {error}", file=sys.stderr)
                code = 1
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_command_matches_the_legacy_powershell_launcher(self) -> None:
        args = launcher.parse_args([])
        command = launcher.build_command(
            Path("llama-server"),
            args,
            Path("m.gguf"),
            Path("p.gguf"),
            "Qwen3.8-27B-Q4_K_M",
        )
        self.assertEqual(
            command, ["llama-server", "--model", "m.gguf", *LEGACY_DEFAULT_ARGUMENTS]
        )

    def test_options_map_to_server_flags(self) -> None:
        args = launcher.parse_args(
            [
                "--model",
                "ridge",
                "--profile",
                "32k",
                "--vision",
                "--no-mtp",
                "--thinking",
                "--port",
                "8081",
                "--host",
                "0.0.0.0",
            ]
        )
        command = launcher.build_command(Path("s"), args, Path("m"), Path("p"), "alias")
        self.assertEqual(command[command.index("--ctx-size") + 1], "32768")
        self.assertEqual(command[command.index("--parallel") + 1], "1")
        self.assertEqual(command[command.index("--mmproj") + 1], "p")
        self.assertEqual(command[command.index("--host") + 1], "0.0.0.0")
        self.assertNotIn("--spec-type", command)
        self.assertNotIn("--reasoning", command)

    def test_invalid_port_and_timeout_are_rejected(self) -> None:
        for argv in (["--port", "0"], ["--port", "70000"], ["--ready-timeout", "0"]):
            with (
                self.subTest(argv=argv),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                launcher.parse_args(argv)
            self.assertEqual(raised.exception.code, 2)

    def test_binary_name_follows_the_platform(self) -> None:
        self.assertEqual(launcher.server_binary_name("nt"), "llama-server.exe")
        self.assertEqual(launcher.server_binary_name("posix"), "llama-server")

    def test_server_resolution_prefers_bundled_then_path_then_fails(self) -> None:
        self.assertEqual(launcher.resolve_server(self.deploy, None), self.server)
        empty = self.root / "empty"
        empty.mkdir()
        on_path = _touch(
            self.root / "bin" / launcher.server_binary_name(), executable=True
        )
        with patch.object(launcher.shutil, "which", return_value=str(on_path)):
            self.assertEqual(launcher.resolve_server(empty, None), on_path.resolve())
        with (
            patch.object(launcher.shutil, "which", return_value=None),
            self.assertRaisesRegex(launcher.LauncherError, "not on PATH"),
        ):
            launcher.resolve_server(empty, None)
        with self.assertRaisesRegex(launcher.LauncherError, "llama-server not found"):
            launcher.resolve_server(empty, empty / "missing")

    @unittest.skipIf(os.name == "nt", "executable bit is POSIX-only")
    def test_non_executable_linux_binary_is_reported(self) -> None:
        self.server.chmod(0o644)
        with self.assertRaisesRegex(launcher.LauncherError, "not executable"):
            launcher.resolve_server(self.deploy, None)

    def test_deployment_root_defaults_to_repo_or_its_parent(self) -> None:
        self.assertEqual(launcher.deployment_root(None, self.repo), self.root)
        (self.repo / "models").mkdir()
        self.assertEqual(launcher.deployment_root(None, self.repo), self.repo)
        with self.assertRaisesRegex(
            launcher.LauncherError, "deployment root not found"
        ):
            launcher.deployment_root(self.root / "missing", self.repo)

    def test_missing_model_and_projector_fail_before_starting(self) -> None:
        with patch.object(launcher, "launch") as launch:
            code, _, stderr = self._run("--vision")
            self.assertEqual(code, 1)
            self.assertIn("mmproj not found", stderr)
            self.model.unlink()
            code, _, stderr = self._run()
            self.assertEqual(code, 1)
            self.assertIn("model file not found", stderr)
        launch.assert_not_called()

    def test_dry_run_prints_command_without_side_effects(self) -> None:
        with patch.object(launcher, "launch") as launch:
            code, stdout, _ = self._run(
                "--dry-run", "--host", "0.0.0.0", "--port", "9001"
            )
        self.assertEqual(code, 0)
        launch.assert_not_called()
        report = json.loads(stdout)
        self.assertEqual(report["server"], str(self.server))
        self.assertEqual(report["endpoint"], "http://127.0.0.1:9001/v1")
        self.assertEqual(report["command"][2], str(self.model))
        self.assertFalse((self.repo / "runtime").exists())

    def test_client_host_maps_wildcard_and_ipv6_binds(self) -> None:
        self.assertEqual(launcher.client_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(launcher.client_host("::"), "[::1]")
        self.assertEqual(launcher.client_host("::1"), "[::1]")
        self.assertEqual(launcher.client_host("10.0.0.5"), "10.0.0.5")

    def test_linux_environment_exposes_bundled_shared_libraries(self) -> None:
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/opt/cuda/lib64"}):
            server = Path("/srv/llama/llama-server")
            environment = launcher.server_environment(server, "posix")
            self.assertEqual(
                environment["LD_LIBRARY_PATH"],
                f"{server.parent}{os.pathsep}/opt/cuda/lib64",
            )
            self.assertEqual(
                launcher.server_environment(Path("C:/llama/llama-server.exe"), "nt")[
                    "LD_LIBRARY_PATH"
                ],
                "/opt/cuda/lib64",
            )

    def _fake_launch(self, mode: str):
        fake = self.root / "fake_llama_server.py"
        fake.write_text(FAKE_SERVER, encoding="utf-8")
        real_launch = launcher.launch
        started: list[subprocess.Popen] = []

        def launch(command, stdout_path, stderr_path, environment):
            environment = {**environment, "FAKE_LLAMA_MODE": mode}
            process = real_launch(
                [sys.executable, str(fake), *command[1:]],
                stdout_path,
                stderr_path,
                environment,
            )
            started.append(process)
            self.addCleanup(launcher.stop, process)
            return process

        return patch.object(launcher, "launch", side_effect=launch), started

    def test_end_to_end_start_waits_for_models_and_leaves_server_running(self) -> None:
        port = _free_port()
        patcher, started = self._fake_launch("serve")
        with patcher, patch.object(launcher, "POLL_SECONDS", 0.1):
            code, stdout, _ = self._run("--port", str(port), "--alias", "qwen-test")
        self.assertEqual(code, 0, stdout)
        self.assertIn(f"ready: pid={started[0].pid}  model_id=qwen-test", stdout)
        self.assertIn(f"FAB_MODEL_BASE_URL=http://127.0.0.1:{port}/v1", stdout)
        self.assertIsNone(started[0].poll())
        self.assertEqual(
            launcher.served_model_id(f"http://127.0.0.1:{port}/v1/models"), "qwen-test"
        )
        logs = sorted((self.repo / "runtime" / "local-model").glob("*.out.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("fake llama-server", logs[0].read_text(encoding="utf-8"))

    def test_early_exit_reports_code_and_log(self) -> None:
        patcher, _ = self._fake_launch("exit")
        with patcher, patch.object(launcher, "POLL_SECONDS", 0.1):
            code, _, stderr = self._run("--port", str(_free_port()))
        self.assertEqual(code, 1)
        self.assertIn("exited with code 3", stderr)
        self.assertIn(".err.log", stderr)

    def test_timeout_stops_the_half_started_server(self) -> None:
        patcher, started = self._fake_launch("hang")
        with patcher, patch.object(launcher, "POLL_SECONDS", 0.1):
            code, _, stderr = self._run(
                "--port", str(_free_port()), "--ready-timeout", "1"
            )
        self.assertEqual(code, 1)
        self.assertIn("did not become ready within 1 seconds", stderr)
        self.assertIsNotNone(started[0].poll())

    def test_cli_entry_point_runs_outside_the_repository(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "start_local_model.py"),
                "--deployment-root",
                str(self.deploy),
                "--dry-run",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["server"], str(self.server))


if __name__ == "__main__":
    unittest.main()
