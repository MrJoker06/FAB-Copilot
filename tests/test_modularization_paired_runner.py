from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "paired_runner", PROJECT / "scripts/modularization_paired_runner.py"
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(runner)


class _Process:
    def __init__(self, code=None):
        self.code = code
        self.terminated = self.killed = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self, timeout=None):
        if self.code is None:
            raise runner.subprocess.TimeoutExpired("fake", timeout)
        return self.code


class _Output:
    def __init__(self, fd):
        self.fd = fd

    def fileno(self):
        return self.fd

    def close(self):
        pass


class ChildTests(unittest.TestCase):
    def _child(self, data=None, closed=False, timeout=0.05):
        read_fd, write_fd = os.pipe()
        if data is not None:
            os.write(write_fd, data)
        if closed:
            os.close(write_fd)
        child = object.__new__(runner.Child)
        child.process = _Process()
        child.stdin = io.BytesIO()
        child.stdout = _Output(read_fd)
        child.timeout, child.buffer = timeout, b""
        child.stderr = io.BytesIO()
        return child, read_fd, write_fd

    def test_invalid_json_and_overlong_and_child_exit_fail_closed(self):
        child, read_fd, _write_fd = self._child(b"nope\n", True)
        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            child.command({"command": "ready"})
        os.close(read_fd)

        child, read_fd, _write_fd = self._child(b"x" * 9, True)
        with (
            mock.patch.object(runner, "MAX_LINE", 8),
            self.assertRaisesRegex(RuntimeError, "maximum"),
        ):
            child.command({"command": "ready"})
        os.close(read_fd)

        child, read_fd, _write_fd = self._child(b"", True)
        with self.assertRaisesRegex(RuntimeError, "exited"):
            child.command({"command": "ready"})
        os.close(read_fd)

    def test_partial_line_timeout_and_cleanup(self):
        child, read_fd, write_fd = self._child(b'{"half"', False, 0.01)
        with self.assertRaises(TimeoutError):
            child.command({"command": "ready"})
        os.close(read_fd)
        os.close(write_fd)

        child, read_fd, write_fd = self._child(b"", False, 0.01)
        child.close()
        self.assertTrue(child.process.terminated)
        os.close(read_fd)
        os.close(write_fd)


class FilesystemTests(unittest.TestCase):
    def test_create_trees_freezes_fixture_from_validated_archive(self):
        protocol = json.loads(
            (PROJECT / "evaluations/mod_002_paired_protocol_v1.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            reference, current, _ = runner.create_trees(
                PROJECT, Path(directory), protocol
            )
            fixture = "scripts/modularization_baseline.py"
            with zipfile.ZipFile(PROJECT / protocol["reference_zip"]) as archive:
                frozen = archive.read(fixture)
            self.assertEqual((reference / fixture).read_bytes(), frozen)
            self.assertEqual((current / fixture).read_bytes(), frozen)
            self.assertTrue((current / "app").is_dir())

    def test_preexisting_report_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runner._reserve_report(path)
            with self.assertRaises(FileExistsError):
                runner.main(["--report", str(path)])
            self.assertEqual(path.read_text(encoding="utf-8"), "keep")

    def test_copy_rejects_symlink_and_only_copies_allowed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / "root", Path(directory) / "out"
            (root / "app/static").mkdir(parents=True)
            (root / "app/a.py").write_text("x", encoding="utf-8")
            (root / "app/static/a.js").write_text("x", encoding="utf-8")
            (root / "app/private.txt").write_text("x", encoding="utf-8")
            (root / "app/private.json").write_text("{}", encoding="utf-8")
            (root / "app/static/.env").write_text("secret", encoding="utf-8")
            (root / "app/static/private.db").write_bytes(b"secret")
            runner._copy_current_app(root, output)
            self.assertTrue((output / "app/a.py").is_file())
            self.assertTrue((output / "app/static/a.js").is_file())
            self.assertFalse((output / "app/private.txt").exists())
            self.assertFalse((output / "app/private.json").exists())
            self.assertFalse((output / "app/static/.env").exists())
            self.assertFalse((output / "app/static/private.db").exists())
            try:
                (root / "app/link.py").symlink_to(root / "app/a.py")
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "symlink"):
                runner._copy_current_app(root, output)

    def test_main_rejects_dangling_report_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.json"
            link = Path(directory) / "link.json"
            link.symlink_to(target)
            with (
                mock.patch.object(runner, "_run") as run,
                self.assertRaises(FileExistsError),
            ):
                runner.main(["--report", str(link)])
            run.assert_not_called()
            self.assertFalse(target.exists())

    def test_failed_run_preserves_partial_evidence_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"

            def fail(_project, _observe, _samples, payload):
                payload["orders"] = [{"partial": "retained"}]
                raise TimeoutError("test timeout")

            with mock.patch.object(runner, "_run", side_effect=fail):
                self.assertEqual(1, runner.main(["--report", str(report)]))
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["status"])
            self.assertEqual([{"partial": "retained"}], payload["orders"])
            self.assertIn("TimeoutError", payload["error"])

    def test_offline_policy_rejects_swallowed_access_or_bool_zero(self):
        for value in (False, 1):
            with self.assertRaises(ValueError):
                runner._offline_policy(
                    {
                        "network_calls": value,
                        "database_calls": 0,
                        "env_files": {"workspace": os.devnull, "project": os.devnull},
                    }
                )


class RunLifecycleTests(unittest.TestCase):
    def _run_with_responses(
        self,
        prepare_overrides=None,
        measure_overrides=None,
        fixture_clocks=None,
        expected_error=None,
    ) -> tuple[mock.Mock, mock.Mock, dict]:
        paired = runner._load(
            "paired_runner_test_baseline",
            PROJECT / "scripts/modularization_paired_baseline.py",
        )
        baseline = json.loads(
            (PROJECT / "evaluations/mod_002_behavior_baseline_v2.json").read_text(
                encoding="utf-8"
            )
        )
        environment = {key: "test" for key in paired.ENVIRONMENT_KEYS}
        policy = {
            "network_calls": 0,
            "database_calls": 0,
            "env_files": {"workspace": os.devnull, "project": os.devnull},
        }
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        reference_tree, current_tree = (
            Path(temporary.name) / "reference-tree",
            Path(temporary.name) / "current-tree",
        )
        reference_tree.mkdir()
        current_tree.mkdir()

        def child_for(tree, overrides):
            child = mock.Mock()
            origins = {"app": [str(tree / "app")]}

            def command(request, _timeout=None):
                fixture_clock = (fixture_clocks or {}).get(
                    request["command"], runner.FIXTURE_CLOCK
                )
                if request["command"] == "ready":
                    return {
                        "environment": environment,
                        "offline_policy": policy,
                        "origins": origins,
                        "fixture_clock": fixture_clock,
                    }
                if request["command"] == "behavior":
                    return {
                        "behavior": baseline,
                        "offline_policy": policy,
                        "origins": origins,
                        "fixture_clock": fixture_clock,
                    }
                if request["command"] == "prepare":
                    response = {
                        "first_run_ns": [1],
                        "warmups_ns": [1] * 10,
                        "cleanup_samples_ns": [0] * 11,
                        "collected_objects": [0] * 11,
                        "offline_policy": policy,
                        "origins": origins,
                        "fixture_clock": fixture_clock,
                    }
                    response.update(prepare_overrides or {})
                    return response
                response = {
                    "wall_samples_ns": [1],
                    "thread_cpu_samples_ns": [0],
                    "process_cpu_samples_ns": [0],
                    "cleanup_samples_ns": [0],
                    "collected_objects": [0],
                    "offline_policy": policy,
                    "origins": origins,
                    "fixture_clock": fixture_clock,
                }
                response.update(overrides or {})
                return response

            child.command.side_effect = command
            return child

        reference = child_for(reference_tree, measure_overrides)
        current = child_for(current_tree, measure_overrides)
        with (
            mock.patch.object(runner, "_load", return_value=paired),
            mock.patch.object(
                runner,
                "create_trees",
                return_value=(
                    reference_tree,
                    current_tree,
                    {"status": "frozen_reference_candidate"},
                ),
            ),
            mock.patch.object(runner, "Child", side_effect=(reference, current)),
        ):
            result = {}
            if expected_error is None:
                runner._run(PROJECT, True, 1, result)
            else:
                with self.assertRaisesRegex(ValueError, expected_error):
                    runner._run(PROJECT, True, 1, result)
        return reference, current, result

    def test_second_child_construction_closes_first_child(self):
        reference = mock.Mock()
        with (
            mock.patch.object(
                runner,
                "create_trees",
                return_value=(
                    PROJECT / "reference-tree",
                    PROJECT / "current-tree",
                    {"status": "frozen_reference_candidate"},
                ),
            ),
            mock.patch.object(
                runner, "Child", side_effect=(reference, RuntimeError("construction"))
            ),
            self.assertRaisesRegex(RuntimeError, "construction"),
        ):
            runner._run(PROJECT, True, 1, {})
        reference.close.assert_called_once_with()

    def test_observe_rejects_invalid_numeric_responses_and_closes_children(self):
        cases = (
            ({"first_run_ns": [False]}, None, "invalid reference prepare response"),
            ({"warmups_ns": [1] * 9 + [0]}, None, "invalid reference prepare response"),
            (
                {"cleanup_samples_ns": [0] * 10 + [float("nan")]},
                None,
                "invalid reference prepare cleanup_samples_ns",
            ),
            (
                {"collected_objects": [0] * 10 + [float("inf")]},
                None,
                "invalid reference prepare collected_objects",
            ),
            (None, {"wall_samples_ns": [False]}, "invalid reference wall_samples_ns"),
            (
                None,
                {"thread_cpu_samples_ns": [-1]},
                "invalid reference thread_cpu_samples_ns",
            ),
            (
                None,
                {"process_cpu_samples_ns": [float("nan")]},
                "invalid reference process_cpu_samples_ns",
            ),
            (
                None,
                {"cleanup_samples_ns": [float("inf")]},
                "invalid reference cleanup_samples_ns",
            ),
            (
                None,
                {"collected_objects": [False]},
                "invalid reference collected_objects",
            ),
        )
        for prepare, measure, expected_error in cases:
            with self.subTest(prepare=prepare, measure=measure):
                reference, current, _ = self._run_with_responses(
                    prepare, measure, expected_error=expected_error
                )
                reference.close.assert_called_once_with()
                current.close.assert_called_once_with()
                commands = [
                    call.args[0]["command"] for call in reference.command.call_args_list
                ]
                self.assertTrue({"ready", "behavior", "prepare"}.issubset(commands))
                if measure is not None:
                    self.assertIn("measure", commands)

    def test_observe_rejects_missing_or_wrong_fixture_clock(self):
        wrong_clock = {**runner.FIXTURE_CLOCK, "runtime_route_date": "2026-08-08"}
        for command, clock in (
            ("ready", {}),
            ("behavior", wrong_clock),
            ("prepare", {}),
            ("measure", wrong_clock),
        ):
            with self.subTest(command=command, clock=clock):
                reference, current, _ = self._run_with_responses(
                    fixture_clocks={command: clock},
                    expected_error="fixture clock does not match frozen inputs",
                )
                reference.close.assert_called_once_with()
                current.close.assert_called_once_with()
                commands = [
                    call.args[0]["command"] for call in reference.command.call_args_list
                ]
                self.assertIn(command, commands)

    def test_observe_accepts_valid_fixture_clock_and_zero_cpu_samples(self):
        reference, current, result = self._run_with_responses()
        self.assertEqual("observed", result["status"])
        self.assertEqual(
            {"reference": runner.FIXTURE_CLOCK, "current": runner.FIXTURE_CLOCK},
            result["fixture_clocks"],
        )
        self.assertEqual(
            {"reference": "", "current": ""}, result["behavior_baseline_diffs"]
        )
        self.assertEqual(
            [0], result["reference"][runner.SCENES[0]]["thread_cpu_samples_ns"][0]
        )
        reference.close.assert_called_once_with()
        current.close.assert_called_once_with()
