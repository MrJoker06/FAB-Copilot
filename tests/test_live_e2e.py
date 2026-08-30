from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.model_streaming import stream_completion
from scripts.live_e2e import enforce_live_bounds, load_live_budgets, load_live_catalog_model, require_live_authorization, resolve_live_budget, sanitized_live_report, scan_isolated_artifacts, write_sanitized_report
from scripts.local_openai_protocol_fixture import LocalOpenAIProtocolFixture, fixture_report
from scripts.run_live_e2e import EXPECTED_LIVE_RUN_COUNT, LIVE_E2E_TARGET_ENV, PROVIDER_MATRIX_LIVE_RUN_COUNT, browser_environment, browser_timeout_seconds, collect_parent_owned_metadata, finalize_report, live_matrix_passes, remaining_duration_seconds, resolve_live_target, validate_live_target_budget
from scripts.run_live_browser_test_server import LIVE_BROWSER_ADMIN_TOKEN, live_browser_environment, live_retry_settings, merge_live_events


async def _notify(_progress, _event): pass


class LiveE2ETests(unittest.TestCase):
    def test_authorization_and_catalog_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "AUTHORIZED"):
            require_live_authorization({})
        with self.assertRaisesRegex(RuntimeError, "API key"):
            require_live_authorization({"FAB_LIVE_E2E_AUTHORIZED": "true", "FAB_LIVE_MODEL_ID": "live"})
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "catalog.db"
            import sqlite3
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE model_catalog(model_id, provider, provider_model, base_url, status, capabilities_json, compatibility_json)")
                connection.execute("INSERT INTO model_catalog VALUES ('live','openai-compatible','provider-live','https://safe.example','published','{\"streaming\":true,\"thinking\":true}','{\"status\":\"passed\"}')")
            model = load_live_catalog_model(db, "live", ("streaming", "thinking"))
            self.assertEqual(model["provider_model"], "provider-live")
            with self.assertRaisesRegex(RuntimeError, "not published"):
                load_live_catalog_model(db, "missing")

    def test_report_is_metadata_only_and_rejects_leakage(self):
        report = sanitized_live_report({"model_id": "live", "provider_model": "provider-live"}, [{"trace_id": "run-1", "status": "success", "answer": "must not persist"}], time.monotonic(), status="passed", model_calls=[{"trace_id": "call-1", "status": "success", "input_tokens": 3, "output_tokens": 5}])
        self.assertNotIn("answer", json.dumps(report))
        self.assertEqual(report["channel"], "LIVE_PROVIDER")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"; write_sanitized_report(target, report)
            self.assertTrue(target.is_file())
            with self.assertRaises(ValueError): write_sanitized_report(target, {"answer": "leak"})
        with self.assertRaisesRegex(RuntimeError, "may only tighten"):
            enforce_live_bounds(report, {"FAB_LIVE_E2E_MAX_MODEL_CALLS": "0"})

    def test_versioned_live_budgets_are_complete_and_overrides_only_tighten(self):
        budgets = load_live_budgets()
        self.assertEqual(set(budgets), {"full", "provider-matrix"})
        full = resolve_live_budget("full", {})
        self.assertEqual(full["expected_run_count"], EXPECTED_LIVE_RUN_COUNT)
        self.assertEqual(resolve_live_budget("provider-matrix", {"FAB_LIVE_E2E_MAX_MODEL_CALLS": "19"})["max_model_calls"], 19)
        for environment in ({"FAB_LIVE_E2E_MAX_MODEL_CALLS": "31"}, {"FAB_LIVE_E2E_MAX_TEST_MS": "many"}):
            with self.assertRaisesRegex(RuntimeError, "budget|integer"):
                resolve_live_budget("full", environment)

    def test_live_target_contract_rejects_budget_run_count_drift_for_both_targets(self):
        for target, expected in (("full", EXPECTED_LIVE_RUN_COUNT), ("provider-matrix", PROVIDER_MATRIX_LIVE_RUN_COUNT)):
            budget = resolve_live_budget(target, {})
            self.assertEqual(validate_live_target_budget(target, expected, budget), expected)
            drifted = dict(budget); drifted["expected_run_count"] += 1
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                validate_live_target_budget(target, expected, drifted)

    def test_total_duration_remaining_time_bounds_browser_and_health_wait(self):
        budget = resolve_live_budget("full", {"FAB_LIVE_E2E_MAX_DURATION_MS": "100", "FAB_LIVE_E2E_MAX_STARTUP_MS": "50", "FAB_LIVE_E2E_MAX_TEST_MS": "90"})
        self.assertAlmostEqual(remaining_duration_seconds(0, budget, clock=lambda: 0.04), 0.06)
        self.assertAlmostEqual(browser_timeout_seconds(0, budget, clock=lambda: 0.04), 0.06)
        with self.assertRaisesRegex(RuntimeError, "exhausted"):
            browser_timeout_seconds(0, budget, clock=lambda: 0.1)

    def test_live_budget_rejects_each_runtime_and_token_boundary(self):
        budget = resolve_live_budget("provider-matrix", {})
        report = sanitized_live_report({"model_id": "live", "provider_model": "provider"}, [], time.monotonic(), status="failed", target="provider-matrix", budget=budget)
        for key, value, error in (("real_model_call_count", budget["max_model_calls"] + 1, "model call"), ("startup_ms", budget["max_startup_ms"] + 1, "startup"), ("test_ms", budget["max_test_ms"] + 1, "test"), ("duration_ms", budget["max_duration_ms"] + 1, "total")):
            broken = dict(report); broken[key] = value
            with self.assertRaisesRegex(RuntimeError, error): enforce_live_bounds(broken, {})
        for key, maximum in (("input", "max_input_tokens"), ("output", "max_output_tokens"), ("total", "max_total_tokens")):
            broken = dict(report); broken["token_totals"] = dict(report["token_totals"]); broken["token_totals"][key] = budget[maximum] + 1
            with self.assertRaisesRegex(RuntimeError, key): enforce_live_bounds(broken, {})
        for key in ("real_model_call_count", "startup_ms", "test_ms", "duration_ms"):
            broken = dict(report); broken[key] = -1
            with self.assertRaises(RuntimeError): enforce_live_bounds(broken, {})
        for key in ("input", "output", "total"):
            broken = dict(report); broken["token_totals"] = dict(report["token_totals"]); broken["token_totals"][key] = -1
            with self.assertRaises(RuntimeError): enforce_live_bounds(broken, {})

    def test_loopback_protocol_fixture_exercises_failures_and_done_requirement(self):
        for scenario, error_type in (("rate_limit", httpx.HTTPStatusError), ("server_error", httpx.HTTPStatusError), ("invalid_json", json.JSONDecodeError), ("missing_done", ValueError), ("partial_disconnect", httpx.RequestError)):
            async def run():
                with LocalOpenAIProtocolFixture(scenario) as fixture:
                    async with httpx.AsyncClient(timeout=0.1) as client:
                        with self.assertRaises(error_type):
                            await stream_completion(client, fixture.url, {}, {"model":"fixture","messages":[]}, None, notify=_notify, disclosure_checker=lambda _: False)
            asyncio.run(run())
            self.assertEqual(fixture_report(scenario, "failed")["channel"], "LOCAL_PROTOCOL_FIXTURE")

    def test_timeout_before_first_body_is_request_error(self):
        async def run():
            with LocalOpenAIProtocolFixture("timeout_before_body") as fixture:
                async with httpx.AsyncClient(timeout=0.05) as client:
                    with self.assertRaises(httpx.RequestError):
                        await stream_completion(client, fixture.url, {}, {"model":"fixture","messages":[]}, None, notify=_notify, disclosure_checker=lambda _: False)
        asyncio.run(run())

    def test_loopback_fixture_selects_bounded_probe_failures_by_request_path(self):
        with LocalOpenAIProtocolFixture("compatibility") as fixture, httpx.Client() as client:
            invalid = client.post(f"{fixture.scenario_base_url('invalid_tool')}/chat/completions", json={"messages": [], "tools": [{"type": "function"}]})
            image = client.post(f"{fixture.scenario_base_url('image_rejected')}/chat/completions", json={"messages": [{"content": [{"type": "image_url"}]}]})
            unavailable = client.post(f"{fixture.scenario_base_url('upstream_unavailable')}/chat/completions", json={"messages": []})
        self.assertEqual(invalid.status_code, 200)
        self.assertIn('\\"ok\\":false', invalid.text)
        self.assertEqual(image.status_code, 422)
        self.assertEqual(unavailable.status_code, 500)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            fixture.scenario_base_url("external")

    def test_leakage_scan_rejects_planted_secret_and_reasoning_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "event.json").write_text('{"reasoning_content":"hidden"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "leakage"):
                scan_isolated_artifacts(root, "live-secret")
            (root / "event.json").write_text("live-secret", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "leakage"):
                scan_isolated_artifacts(root, "live-secret")

    def test_browser_child_environment_is_scrubbed_and_failed_browser_cannot_pass_report(self):
        environment = browser_environment({"FAB_LIVE_MODEL_ID": "live", "FAB_MODEL_API_KEY": "secret", "OTHER_API_KEY": "also-secret", "other_api_key": "lower-secret", "custom_Token": "mixed-secret", "api_key": "bare-key", "TOKEN": "bare-token", "FAB_ADMIN_API_TOKEN": "admin", "KEEP": "yes"}, 8911)
        self.assertEqual(environment["FAB_LIVE_MODEL_ID"], "live")
        self.assertNotIn("FAB_MODEL_API_KEY", environment); self.assertNotIn("FAB_ADMIN_API_TOKEN", environment)
        self.assertNotIn("OTHER_API_KEY", environment)
        self.assertNotIn("other_api_key", environment); self.assertNotIn("custom_Token", environment)
        self.assertNotIn("api_key", environment); self.assertNotIn("TOKEN", environment)
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private.json"
            report = Path(temporary) / "report.json"
            private.write_text(json.dumps({"model": {"model_id": "live", "provider_model": "provider", "provider": "x"}, "runs": [], "model_calls": [{"trace_id": "call", "status": "success"}]}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "validation failed"):
                finalize_report(private, 1, "", time.monotonic(), report_path=report)
            self.assertTrue(report.is_file())

    def test_live_matrix_allows_recovered_attempt_but_rejects_terminal_or_missing_trace_success(self):
        self.assertEqual(EXPECTED_LIVE_RUN_COUNT, 7)
        runs = [{"trace_id": f"run-{index}", "status": "success"} for index in range(7)]
        report = sanitized_live_report({"model_id": "live", "provider_model": "provider"}, runs, time.monotonic(), status="passed", model_calls=[{"trace_id": "run-1", "status": "error"}, *[{"trace_id": f"run-{index}", "status": "success"} for index in range(7)]])
        self.assertTrue(live_matrix_passes(report, report["model_calls"], 0))
        terminal = sanitized_live_report({"model_id": "live", "provider_model": "provider"}, runs, time.monotonic(), status="passed", model_calls=[{"trace_id": f"run-{index}", "status": "success"} for index in range(6)] + [{"trace_id": "run-6", "status": "error"}])
        self.assertFalse(live_matrix_passes(terminal, terminal["model_calls"], 0))
        self.assertFalse(live_matrix_passes(report, report["model_calls"], 1))

    def test_live_target_is_allowlisted_with_a_fixed_provider_matrix_contract(self):
        self.assertEqual(resolve_live_target({}), ("full", [], EXPECTED_LIVE_RUN_COUNT))
        self.assertEqual(resolve_live_target({LIVE_E2E_TARGET_ENV: ""}), ("full", [], EXPECTED_LIVE_RUN_COUNT))
        self.assertEqual(resolve_live_target({LIVE_E2E_TARGET_ENV: "full"}), ("full", [], EXPECTED_LIVE_RUN_COUNT))
        self.assertEqual(
            resolve_live_target({LIVE_E2E_TARGET_ENV: "provider-matrix"}),
            ("provider-matrix", ["--grep", "LIVE-PROVIDER-001"], PROVIDER_MATRIX_LIVE_RUN_COUNT),
        )
        for invalid in (" ", "provider", "LIVE-PROVIDER-001", "provider-matrix "):
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                resolve_live_target({LIVE_E2E_TARGET_ENV: invalid})

    def test_provider_matrix_requires_exactly_five_successful_runs(self):
        runs = [{"trace_id": f"run-{index}", "status": "success"} for index in range(PROVIDER_MATRIX_LIVE_RUN_COUNT)]
        calls = [{"trace_id": f"run-{index}", "status": "success"} for index in range(PROVIDER_MATRIX_LIVE_RUN_COUNT)]
        report = sanitized_live_report(
            {"model_id": "live", "provider_model": "provider"},
            runs,
            time.monotonic(),
            status="passed",
            model_calls=calls,
        )
        self.assertTrue(live_matrix_passes(report, calls, 0, expected_run_count=PROVIDER_MATRIX_LIVE_RUN_COUNT))
        self.assertFalse(live_matrix_passes(report, calls, 0))

    def test_live_metadata_merges_only_fresh_event_runs_without_duplicates(self):
        runs, calls = merge_live_events([
            {"event": "agent_run_finished", "run_id": "live-1", "status": "success"},
            {"event": "model_call_finished", "run_id": "live-1", "status": "success", "phase": "synthesis", "attempt": 2},
            {"event": "model_compatibility_checked", "run_id": "probe-1", "status": "success", "checks": ["connectivity_streaming", "tool_calls", "context_load", "structured_context", "thinking_answer", "thinking_tool_roundtrip", "limits"]},
            {"event": "model_local_fallback_activated", "run_id": "live-1"},
            {"event": "agent_run_finished", "run_id": "live-2", "status": "success", "degraded": True},
        ])
        self.assertEqual({item["trace_id"] for item in runs}, {"live-1", "live-2"})
        self.assertEqual(len(runs), 2); self.assertTrue(next(item for item in runs if item["trace_id"] == "live-1")["fallback"])
        self.assertEqual(len(calls), 7)
        self.assertEqual(calls[0]["attempt"], 2)
        self.assertEqual(calls[1:], [{"status": "success", "phase": "compatibility", "trace_id": "probe-1"}] * 6)
        _, native_calls = merge_live_events([{"event": "model_compatibility_checked", "run_id": "probe-native", "status": "success", "checks": ["connectivity_streaming", "tool_calls", "context_load", "structured_context", "thinking_answer", "thinking_tool_roundtrip", "native_multimodal", "limits"]}])
        self.assertEqual(native_calls, [{"status": "success", "phase": "compatibility", "trace_id": "probe-native"}] * 7)

    def test_live_retry_defaults_overrides_and_safe_attempt_diagnostics(self):
        self.assertEqual(live_retry_settings({}), (4, 1000))
        self.assertEqual(live_retry_settings({"FAB_LIVE_E2E_MODEL_MAX_RETRIES": "2", "FAB_LIVE_E2E_MODEL_RETRY_BASE_MS": "500"}), (2, 500))
        with self.assertRaisesRegex(RuntimeError, "integers"):
            live_retry_settings({"FAB_LIVE_E2E_MODEL_MAX_RETRIES": "many"})
        with self.assertRaisesRegex(RuntimeError, "outside"):
            live_retry_settings({"FAB_LIVE_E2E_MODEL_RETRY_BASE_MS": "10"})
        report = sanitized_live_report({"model_id": "live", "provider_model": "provider"}, [], time.monotonic(), status="failed", model_calls=[{"trace_id": "run", "status": "error", "attempt": 1, "error_type": "ReadTimeout", "failure_reason": "timeout", "retryable": True, "will_retry": True, "answer": "must drop"}])
        self.assertEqual(report["model_calls"][0], {"trace_id": "run", "status": "error", "attempt": 1, "error_type": "ReadTimeout", "failure_reason": "timeout", "retryable": True, "will_retry": True})

    def test_deterministic_fallback_event_is_counted_in_live_report(self):
        runs, _ = merge_live_events([{"event": "agent_run_finished", "run_id": "live-1", "status": "success", "mode": "deterministic-fallback", "answer_synthesis_status": "fallback"}])
        report = sanitized_live_report({"model_id": "live", "provider_model": "provider"}, runs, time.monotonic(), status="passed")
        self.assertEqual(report["fallback_count"], 1)

    def test_server_child_environment_keeps_only_normalized_model_key(self):
        with tempfile.TemporaryDirectory() as temporary, patch("scripts.run_live_browser_test_server.backup_database"), patch("scripts.run_live_browser_test_server.load_live_catalog_model", return_value={"provider": "openai-compatible", "provider_model": "provider", "base_url": "https://model.test", "model_id": "live"}):
            environment = live_browser_environment(Path(temporary), {"FAB_LIVE_E2E_AUTHORIZED": "true", "FAB_LIVE_MODEL_ID": "live", "DEEPSEEK_API_KEY": "secret", "other_api_key": "lower-secret", "custom_Token": "mixed-secret", "API_KEY": "bare-key", "token": "bare-token", "FAB_ADMIN_API_TOKEN": "admin", "FAB_PERSONAL_KNOWLEDGE_API_TOKEN": "personal"})
        self.assertEqual(environment["FAB_MODEL_API_KEY"], "secret")
        self.assertEqual((environment["MODEL_MAX_RETRIES"], environment["MODEL_RETRY_BASE_MS"]), ("4", "1000"))
        self.assertNotIn("DEEPSEEK_API_KEY", environment)
        self.assertEqual(environment["FAB_ADMIN_API_TOKEN"], LIVE_BROWSER_ADMIN_TOKEN)
        self.assertNotEqual(environment["FAB_ADMIN_API_TOKEN"], "admin")
        self.assertNotIn("FAB_PERSONAL_KNOWLEDGE_API_TOKEN", environment)
        self.assertNotIn("other_api_key", environment); self.assertNotIn("custom_Token", environment)
        self.assertNotIn("API_KEY", environment); self.assertNotIn("token", environment)
        self.assertEqual(environment["FAB_DEFAULT_TENANT_ID"], "live-provider-e2e")
        self.assertEqual(environment["FAB_DEFAULT_USER_ID"], "live-provider-e2e-user")
        self.assertTrue(Path(environment["FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH"]).is_relative_to(Path(temporary)))

    def test_parent_owned_root_collects_model_metadata_without_graceful_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); departments = root / "departments"; departments.mkdir()
            import sqlite3
            with sqlite3.connect(departments / "ai_operations.db") as connection:
                connection.execute("CREATE TABLE model_catalog(model_id, provider, provider_model, base_url, status, capabilities_json, compatibility_json)")
                connection.execute("INSERT INTO model_catalog VALUES ('live','openai-compatible','provider-live','https://model.test','published','{}','{\"status\":\"passed\"}')")
            (root / "agent_events.jsonl").write_text(json.dumps({"event": "model_call_finished", "run_id": "live-run", "status": "success", "phase": "synthesis"}) + "\n", encoding="utf-8")
            metadata = collect_parent_owned_metadata(root, "live", "secret", time.monotonic())
            self.assertEqual(metadata["model"]["model_id"], "live")
            self.assertEqual(metadata["model"]["provider_model"], "provider-live")
            self.assertEqual(metadata["model_calls"][0]["trace_id"], "live-run")
