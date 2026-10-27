"""Offline MOD-002 Runtime behavior/performance baseline."""

from __future__ import annotations

import argparse
import asyncio
import copy
import gc
import json
import math
import os
import platform
import statistics
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import date
from difflib import unified_diff
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BEHAVIOR = PROJECT_DIR / "evaluations" / "mod_002_behavior_baseline_v2.json"
DEFAULT_PERFORMANCE = (
    PROJECT_DIR / "evaluations" / "mod_002_performance_baseline_v4.json"
)
REPORT_PATH = PROJECT_DIR / "runtime" / "quality" / "mod_002_comparison_report.json"
VOLATILE_KEYS = frozenset(
    {"run_id", "started_at", "completed_at", "duration_ms", "first_token_ms"}
)
PROXY_ENV_KEYS = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    }
)
PROXY_ENVIRONMENT = "excluded_inside_offline_fixture"
GC_POLICY = "collect_before_each_fixture_sample_auto_gc_enabled"
FORMAL_CLI_SAMPLES_PER_BATCH = 1000
FORMAL_CLI_BATCHES = 2
SCENES = ("ready_success", "loop_success", "knowledge_retrieval_success")
FIXTURE_DATE = date(2026, 8, 7)
sys.path.insert(0, str(PROJECT_DIR))
# These imports intentionally follow the project-root path insertion.
from fastapi.routing import APIRoute

from app.agent_runtime import service as agent
from app.agent_runtime.service import TOOLS
from app.main import app
from scripts.evaluate_trace_replay import load_dataset, replay_case
from scripts.modularization_fixture_clock import fixed_capture_clock
from scripts.refactor_contracts import collect_frontend_contract


def canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def normalize(v: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(v, dict):
        lifecycle = bool(path and path[-1] in {"progress_events", "tool_trace"})
        normalized = {
            k: normalize(x, path + (k,))
            for k, x in v.items()
            if not (lifecycle and k in VOLATILE_KEYS)
        }
        if path and path[-1] == "model_messages" and normalized.get("role") == "system":
            content = normalized.get("content")
            marker = "\nanswer_contract="
            if isinstance(content, str) and marker in content:
                prefix, contract = content.split(marker, 1)
                try:
                    contract_object = json.loads(contract)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(contract_object, dict):
                        normalized["content"] = (
                            prefix
                            + marker
                            + json.dumps(
                                contract_object,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                        )
        return normalized
    return [normalize(x, path) for x in v] if isinstance(v, list) else v


def percentile_nearest_rank(s: list[int], p: int) -> int:
    if not s or not 0 < p <= 100:
        raise ValueError("samples must be non-empty and percentile must be 1..100")
    return sorted(s)[(len(s) * p + 99) // 100 - 1]


class FixtureGuard:
    def __init__(self):
        self.network_calls = 0
        self.database_calls = 0

    def network(self, *a, **k):
        self.network_calls += 1
        raise AssertionError("MOD-002 fixture attempted external network access")

    def database(self, *a, **k):
        self.database_calls += 1
        raise AssertionError("MOD-002 fixture attempted database access")

    def assert_clean(self):
        if self.network_calls or self.database_calls:
            raise AssertionError(
                f"MOD-002 fixture forbidden access: network_calls={self.network_calls}, database_calls={self.database_calls}"
            )


@contextmanager
def fixture_guard() -> Iterator[FixtureGuard]:
    g = FixtureGuard()
    with ExitStack() as s:
        for target in (
            "socket.create_connection",
            "socket.socket.connect",
            "socket.socket.connect_ex",
        ):
            s.enter_context(patch(target, new=g.network))
        s.enter_context(patch("sqlite3.connect", new=g.database))
        yield g
    g.assert_clean()


@contextmanager
def fixture_proxy_environment() -> Iterator[None]:
    retained_environment = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    with patch.dict(os.environ, retained_environment, clear=True):
        yield


class _FixtureDate(date):
    @classmethod
    def today(cls):
        return FIXTURE_DATE


def _settings():
    return SimpleNamespace(
        model_connection=SimpleNamespace(
            provider="mod002-fixture",
            api_key="fixture",
            base_url="https://offline.invalid",
            model="fixture",
        ),
        api_timeout_seconds=1,
        model_max_retries=0,
        model_retry_base_seconds=0.0,
    )


def _handler(name, fail=False):
    def execute(**arguments):
        if fail:
            raise RuntimeError("synthetic capability failure")
        row = {"fixture": "MOD-002", "tool": name, "arguments": arguments}
        if name == "search_knowledge":
            row.update(
                {
                    "reference_id": "KB-MOD002-001",
                    "source_type": "knowledge",
                    "content": "synthetic retrieval evidence",
                    "retrieval": {"confidence": "high", "score": 0.99},
                }
            )
        return [row]

    return execute


def _ready_handlers(fail_first=False, empty_knowledge=False):
    d = {
        n: _handler(n, fail_first and n == "get_process_capability")
        for n in (
            "get_process_capability",
            "get_recent_excursions",
            "get_sensor_summary",
            "search_knowledge",
        )
    }
    if empty_knowledge:
        d["search_knowledge"] = lambda **k: []
    return d


async def _capture_ready(
    *,
    failure=False,
    retrieval_only=False,
    empty_knowledge=False,
    handler_overrides=None,
    environment_observer=None,
):
    question = (
        "解释一下化学机械抛光的基本原理"
        if retrieval_only
        else "分析 2026-08-01 至 2026-08-07 CMP-03 Cpk 不合格"
    )
    events = []
    requests = []

    async def stream(_c, _e, _h, p, _pr, _st):
        if environment_observer:
            environment_observer()
        requests.append(copy.deepcopy(p))
        return (
            {"role": "assistant", "content": "离线合成结论。"},
            {"total_tokens": 3},
            "fixture",
        )

    async def progress(e):
        events.append(copy.deepcopy(e))

    h = _ready_handlers(failure, empty_knowledge)
    h.update(handler_overrides or {})
    with ExitStack() as s:
        s.enter_context(
            patch("app.agent_runtime.service.get_settings", return_value=_settings())
        )
        s.enter_context(
            patch("app.agent_runtime.service._stream_completion", new=stream)
        )
        s.enter_context(patch("app.agent_runtime.service.emit"))
        s.enter_context(patch("app.intent_runtime.routing.date", new=_FixtureDate))
        s.enter_context(patch.dict(agent.TOOL_HANDLERS, h, clear=True))
        with fixture_proxy_environment(), fixture_guard():
            started = time.perf_counter_ns()
            result = await agent._run_agent_impl(question, [], "mod002-run", progress)
            elapsed = time.perf_counter_ns() - started
    return {
        "runtime_entry": "_run_agent_impl",
        "question": question,
        "events": events,
        "model_requests": requests,
        "result": result,
        "elapsed_runtime_ns": elapsed,
    }


async def _capture_loop(
    *,
    duplicate=True,
    knowledge=False,
    empty=False,
    handler_overrides=None,
    environment_observer=None,
):
    events = []
    requests = []
    round_no = 0
    tool = "search_knowledge" if knowledge else "get_process_capability"
    args = (
        {
            "query": "化学机械抛光基本原理",
            "source_types": ["personal", "knowledge"],
            "limit": 5,
        }
        if knowledge
        else {"start": "2026-08-01", "end": "2026-08-07", "process_step": "CMP"}
    )

    async def stream(_c, _e, _h, p, _pr, _st):
        nonlocal round_no
        round_no += 1
        if environment_observer:
            environment_observer()
        requests.append(copy.deepcopy(p))
        if knowledge:
            content = (
                "知识库未返回可用内容；以下为通用原理说明。"
                if empty
                else "化学机械抛光结合化学反应与机械作用实现表面平坦化。[来源 KB-MOD002-001]"
            )
            return (
                {"role": "assistant", "content": content},
                {"total_tokens": 2},
                "fixture",
            )
        if round_no <= (3 if duplicate else 1):
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"fixture-{round_no}",
                            "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(args)},
                        }
                    ],
                },
                {"total_tokens": 2},
                "fixture",
            )
        return (
            {
                "role": "assistant",
                "content": "知识库未返回可用内容，以下为通用原理说明。"
                if empty
                else "已有证据不足，已停止重复查询。"
                if duplicate
                else "离线 Loop 工具调用完成。",
            },
            {"total_tokens": 2},
            "fixture",
        )

    async def progress(e):
        events.append(copy.deepcopy(e))

    h = {tool: (lambda **k: []) if empty else _handler(tool)}
    h.update(handler_overrides or {})
    q = (
        "解释一下化学机械抛光的基本原理"
        if knowledge
        else "分析 2026-08-01 至 2026-08-07 CMP 划伤缺陷 Pareto"
    )
    with ExitStack() as s:
        s.enter_context(
            patch("app.agent_runtime.service.get_settings", return_value=_settings())
        )
        s.enter_context(
            patch("app.agent_runtime.service._stream_completion", new=stream)
        )
        s.enter_context(patch("app.agent_runtime.service.emit"))
        s.enter_context(patch("app.intent_runtime.routing.date", new=_FixtureDate))
        s.enter_context(patch.dict(agent.TOOL_HANDLERS, h, clear=True))
        with fixture_proxy_environment(), fixture_guard():
            started = time.perf_counter_ns()
            result = await agent._run_agent_impl(q, [], "mod002-loop", progress)
            elapsed = time.perf_counter_ns() - started
    return {
        "runtime_entry": "_run_agent_impl",
        "question": q,
        "events": events,
        "model_requests": requests,
        "result": result,
        "elapsed_runtime_ns": elapsed,
    }


def _summary(c):
    r = c["result"]
    req = c["model_requests"]
    return {
        "execution_layer": c["runtime_entry"],
        "input": {"question": c["question"]},
        "model_request_count": len(req),
        "model_tool_names": [
            [x["function"]["name"] for x in p.get("tools", [])] for p in req
        ],
        "model_messages": [p.get("messages", []) for p in req],
        "progress_events": c["events"],
        "tool_trace": r.get("tool_trace", []),
        "loop_guard": r.get("loop_guard", {}),
        "execution_mode": r.get("execution_mode"),
        "mode": r.get("mode"),
        "sources": r.get("sources", []),
        "evidence_validation": r.get("evidence_validation", {}),
        "answer_synthesis": r.get("answer_synthesis", {}),
        "answer": r.get("answer", ""),
        "execution_plan": r.get("execution_plan", {}),
        "intent_route": r.get("intent_route", {}),
        "answer_contract": r.get("answer_contract", {}),
        "retrieval_decision": r.get("retrieval_decision", {}),
        "knowledge_fallback": r.get("knowledge_fallback", {}),
        "turn_decision": r.get("turn_decision", {}),
    }


def _api_snapshot():
    rs = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            rs += [
                {
                    "method": m,
                    "name": r.name,
                    "path": r.path,
                    "success_status": r.status_code or 200,
                }
                for m in sorted(r.methods or [])
            ]
    return {
        "openapi": copy.deepcopy(app.openapi()),
        "routes": sorted(rs, key=lambda x: (x["path"], x["method"])),
    }


def _policy_snapshot():
    d = load_dataset()
    today = date.fromisoformat(d["current_date"])
    return {
        "execution_layer": "policy_replay",
        "dataset_id": d["dataset_id"],
        "cases": {
            c["id"]: normalize(
                {
                    "execution_layer": "policy_replay",
                    "question": c["question"],
                    "result": replay_case(c, current_date=today),
                }
            )
            for c in d["cases"]
        },
    }


@fixed_capture_clock()
def collect_behavior():
    cs = {
        "ready_success": _capture_ready(),
        "ready_dependency_failure": _capture_ready(failure=True),
        "loop_success": _capture_loop(duplicate=False),
        "loop_duplicate_blocked": _capture_loop(),
        "knowledge_retrieval_success": _capture_loop(duplicate=False, knowledge=True),
        "knowledge_retrieval_empty_degraded": _capture_loop(
            duplicate=False, knowledge=True, empty=True
        ),
    }
    return normalize(
        {
            "schema_version": "1.2",
            "current_date": FIXTURE_DATE.isoformat(),
            "data_classification": "synthetic_redacted",
            "execution_policy": {
                "network_calls": 0,
                "real_model_calls": 0,
                "database_calls": 0,
            },
            "normalization": {
                "removed_fields": sorted(VOLATILE_KEYS),
                "rule": "Only direct Runtime trace/event lifecycle fields are removed. In model_messages, only system-message legal JSON objects after the exact newline answer_contract marker are key-sorted; nested business fields, user messages, arrays, malformed JSON, and other message content are retained.",
            },
            "contracts": {
                "tools": copy.deepcopy(TOOLS),
                "api": _api_snapshot(),
                "frontend": collect_frontend_contract(),
                "policy_replay": _policy_snapshot(),
            },
            "scenarios": {k: _summary(asyncio.run(v)) for k, v in cs.items()},
        }
    )


def _measure(n, s):
    a = {
        "ready_success": lambda: _capture_ready(),
        "loop_success": lambda: _capture_loop(duplicate=False),
        "knowledge_retrieval_success": lambda: _capture_loop(
            duplicate=False, knowledge=True
        ),
    }[n]

    def capture_after_cleanup():
        cleanup_started_ns = time.perf_counter_ns()
        collected = gc.collect()
        cleanup_ns = time.perf_counter_ns() - cleanup_started_ns
        capture = asyncio.run(a())
        return int(capture["elapsed_runtime_ns"]), cleanup_ns, collected

    first_run_ns, first_cleanup_ns, first_collected_objects = capture_after_cleanup()
    cleanup_samples_ns = [first_cleanup_ns]
    collected_objects = [first_collected_objects]
    for _ in range(10):
        _, cleanup_ns, collected = capture_after_cleanup()
        cleanup_samples_ns.append(cleanup_ns)
        collected_objects.append(collected)
    samples_ns = []
    for _ in range(s):
        elapsed_runtime_ns, cleanup_ns, collected = capture_after_cleanup()
        samples_ns.append(elapsed_runtime_ns)
        cleanup_samples_ns.append(cleanup_ns)
        collected_objects.append(collected)
    return {
        "first_run_ns": first_run_ns,
        "samples_ns": samples_ns,
        "cleanup_samples_ns": cleanup_samples_ns,
        "collected_objects": collected_objects,
    }


def collect_performance(samples=30, batches=1):
    if not gc.isenabled():
        raise RuntimeError("performance collection requires automatic GC to be enabled")
    if (
        isinstance(samples, bool)
        or isinstance(batches, bool)
        or not isinstance(samples, int)
        or not isinstance(batches, int)
        or samples < 30
        or batches < 1
    ):
        raise ValueError("samples must be >=30 and batches positive integers")
    out = {}
    for n in SCENES:
        measurements = [_measure(n, samples) for _ in range(batches)]
        runs = [item["samples_ns"] for item in measurements]
        med = [int(statistics.median(x)) for x in runs]
        spread = (max(med) - min(med)) / max(1, min(med))
        flat = [x for run in runs for x in run]
        cleanup_runs = [item["cleanup_samples_ns"] for item in measurements]
        cleanup_flat = [x for run in cleanup_runs for x in run]
        out[n] = {
            "warmups_per_batch": 10,
            "samples_per_batch": samples,
            "batches": batches,
            "first_run_ns": [item["first_run_ns"] for item in measurements],
            "first_run_note": "first fixture-sequence Runtime call before warmups; not fresh-process cold import",
            "raw_samples_ns": runs,
            "cleanup_samples_ns": cleanup_runs,
            "collected_objects": [item["collected_objects"] for item in measurements],
            "cleanup_median_ns": int(statistics.median(cleanup_flat)),
            "cleanup_p95_ns": percentile_nearest_rank(cleanup_flat, 95),
            "batch_median_ns": med,
            "batch_p95_ns": [percentile_nearest_rank(x, 95) for x in runs],
            "median_ns": int(statistics.median(flat)),
            "p95_ns": percentile_nearest_rank(flat, 95),
            "observed_spread_pct": round(spread * 100, 2),
            "relative_allowance_pct": round(spread * 100 + 15, 2),
        }
    return {
        "schema_version": "1.3",
        "measurement": {
            "clock": "perf_counter_ns",
            "percentile": "nearest-rank",
            "cold_import": "not measured; imports occur before timing; first_run_ns is fixture-sequence only",
            "timed_region": "only _run_agent_impl after fixture patches; includes Runtime HTTP-client construction, mocked request and progress recording",
            "relative_allowance_policy": "relative_allowance_pct is a 15 percentage-point policy allowance plus observed batch spread; it is not inferred solely from measurement noise",
            "proxy_environment": PROXY_ENVIRONMENT,
            "gc_policy": GC_POLICY,
            "formal_cli_default_sampling": f"{FORMAL_CLI_SAMPLES_PER_BATCH} samples per batch; {FORMAL_CLI_BATCHES} batches",
            "status": "candidate_calibration"
            if samples >= 100 and batches >= 2
            else "observation",
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "os": platform.platform(),
            "machine": platform.machine(),
            "node": platform.node(),
            "httpx": __import__("httpx").__version__,
            "proxy_environment": PROXY_ENVIRONMENT,
            "gc_policy": GC_POLICY,
        },
        "scenarios": out,
    }


def diff(e, a, l):
    return "".join(
        unified_diff(
            canonical(e).splitlines(True),
            canonical(a).splitlines(True),
            fromfile="expected/" + l,
            tofile="actual/" + l,
        )
    )


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _positive_number(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _schema_errors(x):
    es = []
    if not isinstance(x, dict):
        return ["payload is not an object"]
    if x.get("schema_version") != "1.3":
        es.append("unsupported performance schema")
    measurement = x.get("measurement")
    if not isinstance(measurement, dict):
        es.append("missing measurement metadata")
    else:
        if measurement.get("clock") != "perf_counter_ns":
            es.append("invalid measurement.clock")
        if measurement.get("percentile") != "nearest-rank":
            es.append("invalid measurement.percentile")
        if (
            not isinstance(measurement.get("timed_region"), str)
            or not measurement["timed_region"]
        ):
            es.append("invalid measurement.timed_region")
        if measurement.get("proxy_environment") != PROXY_ENVIRONMENT:
            es.append("invalid measurement.proxy_environment")
        if measurement.get("gc_policy") != GC_POLICY:
            es.append("invalid measurement.gc_policy")
        if measurement.get("formal_cli_default_sampling") != (
            f"{FORMAL_CLI_SAMPLES_PER_BATCH} samples per batch; {FORMAL_CLI_BATCHES} batches"
        ):
            es.append("invalid measurement.formal_cli_default_sampling")
        status = measurement.get("status")
        if not isinstance(status, str) or status not in {
            "observation",
            "candidate_calibration",
            "approved_gate",
        }:
            es.append("invalid measurement.status")
    environment = x.get("environment")
    if not isinstance(environment, dict):
        es.append("missing environment")
    elif any(
        not isinstance(environment.get(key), str) or not environment[key]
        for key in (
            "python",
            "implementation",
            "os",
            "machine",
            "node",
            "httpx",
            "proxy_environment",
            "gc_policy",
        )
    ):
        es.append("invalid environment")
    scenarios = x.get("scenarios")
    if not isinstance(scenarios, dict):
        return es + ["scenarios must be an object"]
    if set(scenarios) != set(SCENES):
        es.append("scenario set must exactly match required scenes")
    for n in SCENES:
        d = scenarios.get(n)
        if not isinstance(d, dict):
            es.append(f"invalid scenario {n}")
            continue
        for k in ("median_ns", "p95_ns"):
            if not _positive_number(d.get(k)):
                es.append(f"invalid {n}.{k}")
        for k in ("samples_per_batch", "batches"):
            if isinstance(d.get(k), bool) or not isinstance(d.get(k), int) or d[k] < 1:
                es.append(f"invalid {n}.{k}")
        allowance = d.get("relative_allowance_pct")
        if (
            isinstance(allowance, bool)
            or not isinstance(allowance, (int, float))
            or not math.isfinite(allowance)
            or allowance < 0
        ):
            es.append(f"invalid {n}.relative_allowance_pct")
    return es


def compare_performance(e, a):
    errors = _schema_errors(e) + _schema_errors(a)
    if errors:
        return "performance baseline invalid: " + "; ".join(errors) + "\n"
    if e["environment"] != a["environment"]:
        return "performance baseline incomparable: environment differs\n"
    if e["measurement"].get("timed_region") != a["measurement"].get("timed_region"):
        return "performance baseline incomparable: timing definition differs\n"
    if e["measurement"].get("status") != "approved_gate":
        return "performance baseline not an approved frozen gate\n"
    for label, payload in (("expected", e), ("actual", a)):
        for n in SCENES:
            d = payload["scenarios"][n]
            if d["samples_per_batch"] < 100 or d["batches"] < 2:
                return f"performance baseline invalid: {label}.{n} approved gate requires samples_per_batch >= 100 and batches >= 2\n"
    failures = []
    for n in SCENES:
        f, c = e["scenarios"][n], a["scenarios"][n]
        allow = f.get("relative_allowance_pct", -1)
        if not isinstance(allow, (int, float)) or allow < 0:
            failures.append(f"{n}: invalid relative allowance")
            continue
        for k in ("median_ns", "p95_ns"):
            if c[k] > int(f[k] * (1 + allow / 100)):
                failures.append(
                    f"{n}.{k}: regression exceeds {allow}% relative allowance plus observed spread"
                )
    return "\n".join(failures) + ("\n" if failures else "")


def _write_new(p, v, replace=False):
    if p.exists() and not replace:
        raise FileExistsError(f"capture refuses to overwrite {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(canonical(v), encoding="utf-8", newline="\n")


def main():
    q = argparse.ArgumentParser()
    q.add_argument("--mode", choices=("compare", "capture"), default="compare")
    q.add_argument("--behavior", type=Path, default=DEFAULT_BEHAVIOR)
    q.add_argument("--performance", type=Path, default=DEFAULT_PERFORMANCE)
    q.add_argument(
        "--performance-samples", type=int, default=FORMAL_CLI_SAMPLES_PER_BATCH
    )
    q.add_argument("--performance-batches", type=int, default=FORMAL_CLI_BATCHES)
    q.add_argument("--replace-behavior", action="store_true")
    q.add_argument("--skip-performance", action="store_true")
    a = q.parse_args()
    if a.mode == "capture":
        bad = [
            p
            for p in [a.behavior] + ([] if a.skip_performance else [a.performance])
            if p.exists() and not (p == a.behavior and a.replace_behavior)
        ]
        if bad:
            raise FileExistsError(
                "capture refuses to overwrite " + ", ".join(map(str, bad))
            )
    b = collect_behavior()
    perf = (
        None
        if a.skip_performance
        else collect_performance(a.performance_samples, a.performance_batches)
    )
    if a.mode == "capture":
        _write_new(a.behavior, b, a.replace_behavior)
        perf is not None and _write_new(a.performance, perf)
        print("captured MOD-002 baselines")
        return 0
    bd = diff(load_json(a.behavior), b, a.behavior.name)
    pd = "" if perf is None else compare_performance(load_json(a.performance), perf)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        canonical(
            {
                "behavior": {"status": "passed" if not bd else "different", "diff": bd},
                "performance": {
                    "status": "skipped"
                    if perf is None
                    else ("passed" if not pd else "not_passed"),
                    "comparison": pd,
                    "actual": perf,
                },
                "environment": None if perf is None else perf["environment"],
            }
        ),
        encoding="utf-8",
    )
    if bd or pd:
        print(bd or pd)
        return 1
    print(
        "MOD-002 behavior baseline passed."
        if perf is None
        else "MOD-002 behavior and performance baselines passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
