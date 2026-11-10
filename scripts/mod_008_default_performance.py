"""Isolated MOD-008 F2b observation of default native-v2 versus frozen v1.

This is a migration report, not a MOD-002 formal-pass claim.  It reuses the
approved archive extraction/validation helper but adds no digest scheme.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from contextvars import copy_context
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = PROJECT / "evaluations/mod_002_paired_protocol_v1.json"
SCENES = ("ready_success", "loop_success", "knowledge_retrieval_success")
ALLOWANCES = {
    "ready_success": 15.65,
    "loop_success": 16.36,
    "knowledge_retrieval_success": 15.64,
}
FORMAL_SAMPLES, FORMAL_BATCHES, WARMUPS, BLOCK = 1000, 2, 10, 50
OBSERVER_PROFILE = "minimal-counts-v1"
MAX_LINE = 2_000_000


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("mod008_pair_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _protocol() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if set(protocol.get("scenarios", {})) != set(SCENES):
        raise RuntimeError("unexpected MOD-002 scenario set")
    for scene, allowance in ALLOWANCES.items():
        if protocol["scenarios"][scene].get("relative_allowance_pct") != allowance:
            raise RuntimeError(f"frozen allowance changed: {scene}")
    return protocol


def _require_sampling(samples: int, batches: int, formal: bool) -> None:
    if type(samples) is not int or type(batches) is not int:
        raise TypeError("counts must be integers")
    if formal and (samples, batches) != (FORMAL_SAMPLES, FORMAL_BATCHES):
        raise ValueError("--formal requires exactly 1000 samples and 2 batches")
    if not formal and (samples < 30 or batches < 1):
        raise ValueError("observation requires at least 30 samples and one batch")
    if samples % BLOCK:
        raise ValueError("samples must be divisible by the 50-sample AB/BA block")


def _p95(values: list[int]) -> int:
    if not values:
        raise ValueError("empty samples")
    return sorted(values)[(len(values) * 95 + 99) // 100 - 1]


def _orders(samples: int, batches: int) -> list[dict[str, Any]]:
    return [
        {
            "scene": scene,
            "batch": batch,
            "block": block,
            "count": BLOCK,
            "sides": ["reference", "current"]
            if (batch + block) % 2 == 0
            else ["current", "reference"],
        }
        for scene in SCENES
        for batch in range(batches)
        for block in range(samples // BLOCK)
    ]


class Child:
    """Line IPC worker with a clean environment and an isolated app root."""

    def __init__(self, tree: Path, script: Path) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("FAB_", "DEEPSEEK_"))
            and k not in {"PYTHONPATH", "DATABASE_URL", "DB_URL", "LOG_FILE"}
        }
        env = {
            k: v
            for k, v in env.items()
            if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
        }
        env["FAB_WORKSPACE_ENV_FILE"] = os.devnull
        env["FAB_PROJECT_ENV_FILE"] = os.devnull
        self.process = subprocess.Popen(
            [sys.executable, "-I", str(script), "--worker", "--project-dir", str(tree)],
            cwd=tree,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=env,
        )
        assert self.process.stdin and self.process.stdout

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        self.process.stdin.write(
            (json.dumps(request, separators=(",", ":")) + "\n").encode()
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline(MAX_LINE + 1)
        if not line or len(line) > MAX_LINE:
            raise RuntimeError("worker returned no bounded JSON")
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise RuntimeError(response.get("error", "worker failure"))
        return response

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.call({"command": "stop"})
            except (OSError, RuntimeError, ValueError):
                self.process.terminate()
        self.process.wait(timeout=10)


def _empty(batches: int) -> dict[str, list[list[int]]]:
    return {
        key: [[] for _ in range(batches)]
        for key in (
            "wall_samples_ns",
            "thread_cpu_samples_ns",
            "process_cpu_samples_ns",
            "cleanup_samples_ns",
            "collected_objects",
        )
    }


def _valid(value: object, samples: int, batches: int) -> bool:
    if not isinstance(value, dict):
        return False
    for key in _empty(batches):
        rows = value.get(key)
        if (
            not isinstance(rows, list)
            or len(rows) != batches
            or any(
                not isinstance(r, list)
                or len(r) != samples
                or any(type(x) is not int or x < 0 for x in r)
                for r in rows
            )
        ):
            return False
    return all(x > 0 for row in value["wall_samples_ns"] for x in row)


def run(samples: int, batches: int, formal: bool) -> dict[str, Any]:
    _require_sampling(samples, batches, formal)
    protocol = _protocol()
    with tempfile.TemporaryDirectory(prefix="mod008-default-native-") as temp:
        # Existing helper validates the approved archive and safely extracts it.
        reference, current, metadata = _load(
            PROJECT / "scripts/modularization_paired_runner.py"
        ).create_trees(PROJECT, Path(temp), protocol)
        children = {}
        try:
            for side, tree in (("reference", reference), ("current", current)):
                children[side] = Child(tree, Path(__file__).resolve())
            data = {
                side: {
                    "setup": child.call({"command": "setup", "side": side}),
                    "measurements": {},
                }
                for side, child in children.items()
            }
            for item in _orders(samples, batches):
                for side in item["sides"]:
                    block = children[side].call(
                        {
                            "command": "measure",
                            "side": side,
                            "scene": item["scene"],
                            "count": item["count"],
                            "batch": item["batch"],
                        }
                    )["measurement"]
                    out = data[side]["measurements"].setdefault(
                        item["scene"], _empty(batches)
                    )
                    for key, values in block.items():
                        out[key][item["batch"]].extend(values)
            for side, child in children.items():
                data[side]["finish"] = child.call({"command": "finish"})
        finally:
            for child in children.values():
                child.close()
    for scene in SCENES:
        reference_proof = data["reference"]["finish"]["proofs"][scene]
        current_proof = data["current"]["finish"]["proofs"][scene]
        for key in (
            "question",
            "business",
            "tools",
            "model_calls",
            "guard_calls",
            "audit",
            "usable_knowledge",
        ):
            if reference_proof[key] != current_proof[key]:
                raise AssertionError(f"migration fixture differs: {scene}.{key}")
    comparison = {}
    for scene in SCENES:
        ref, cur = (
            data["reference"]["measurements"][scene],
            data["current"]["measurements"][scene],
        )
        if not _valid(ref, samples, batches) or not _valid(cur, samples, batches):
            raise RuntimeError(f"invalid proof samples: {scene}")
        a, b = (
            [x for r in ref["wall_samples_ns"] for x in r],
            [x for r in cur["wall_samples_ns"] for x in r],
        )
        batch_stats = []
        for batch in range(batches):
            reference, current = (
                ref["wall_samples_ns"][batch],
                cur["wall_samples_ns"][batch],
            )
            ref_median, cur_median = (
                int(statistics.median(reference)),
                int(statistics.median(current)),
            )
            ref_p95, cur_p95 = _p95(reference), _p95(current)
            median_delta = (cur_median - ref_median) * 100 / max(1, ref_median)
            p95_delta = (cur_p95 - ref_p95) * 100 / max(1, ref_p95)
            batch_stats.append(
                {
                    "batch": batch,
                    "reference_v1": {"median_ns": ref_median, "p95_ns": ref_p95},
                    "default_native_v2": {"median_ns": cur_median, "p95_ns": cur_p95},
                    "median_delta_pct": round(median_delta, 4),
                    "p95_delta_pct": round(p95_delta, 4),
                    "median_within_legacy_allowance": median_delta <= ALLOWANCES[scene],
                    "p95_within_legacy_allowance": p95_delta <= ALLOWANCES[scene],
                }
            )
        median_a, median_b = int(statistics.median(a)), int(statistics.median(b))
        p95_a, p95_b = _p95(a), _p95(b)
        median_delta = (median_b - median_a) * 100 / max(1, median_a)
        p95_delta = (p95_b - p95_a) * 100 / max(1, p95_a)
        comparison[scene] = {
            "allowance_pct": ALLOWANCES[scene],
            "batches": batch_stats,
            "reference_v1": {"median_ns": median_a, "p95_ns": p95_a},
            "default_native_v2": {"median_ns": median_b, "p95_ns": p95_b},
            "median_delta_pct": round(median_delta, 4),
            "p95_delta_pct": round(p95_delta, 4),
            "median_within_legacy_allowance": all(
                item["median_within_legacy_allowance"] for item in batch_stats
            ),
            "p95_within_legacy_allowance": all(
                item["p95_within_legacy_allowance"] for item in batch_stats
            ),
        }
    passed = all(
        item["median_within_legacy_allowance"] and item["p95_within_legacy_allowance"]
        for item in comparison.values()
    )
    return {
        "schema_version": "1.0",
        "kind": "MOD-008 F2b capability-2 migration observation",
        "not_mod_002_formal_pass": True,
        "status": "passed" if passed else "failed",
        "observer_profile": OBSERVER_PROFILE,
        "worker_lifecycle": "steady-worker-loop-v1",
        "reference_sources": "actual frozen report/RAG handlers with governed Fake sources",
        "limits": "v1/v2 differ by approved schemas, catalog, native source, trace/version and planner ids; this comparison does not claim behavioral equivalence.",
        "protocol": {
            "reference_id": protocol["reference_id"],
            "archive_metadata": metadata,
            "allowances_pct": ALLOWANCES,
        },
        "sampling": {
            "samples_per_batch": samples,
            "batches": batches,
            "warmups_per_batch": WARMUPS,
            "block_size": BLOCK,
            "formal": formal,
            "order": _orders(samples, batches),
        },
        "sides": data,
        "comparison": comparison,
    }


# Fixed input contract declared before measurement.  Both workers use these exact
# questions and complete business rows; version/source metadata may differ.
QUESTIONS = {
    "ready_success": "分析 2026-08-01 至 2026-08-07 CMP Cpk 不合格",
    # A question without a deterministic playbook keeps the legacy loop path;
    # the scripted model call below still exercises get_defect_pareto.
    "loop_success": "数据接口有哪些",
    "knowledge_retrieval_success": "解释一下化学机械抛光的基本原理",
}
ROWS = {
    "get_process_capability": [
        {
            "process_step": "CMP",
            "equipment_id": "CMP-03",
            "samples": 4,
            "mean_value": 10.5,
            "sigma": 0.5,
            "min_value": 10.0,
            "max_value": 11.0,
            "cpk": 1.0,
            "metric_name": "thickness",
            "metric_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 12.0,
        }
    ],
    "get_sensor_summary": [
        {
            "process_step": "CMP",
            "equipment_id": "CMP-03",
            "signal_name": "pressure",
            "signal_unit": "kPa",
            "samples": 4,
            "missing_samples": 0,
            "flagged_outliers": 1,
            "mean_value": 10.5,
            "min_value": 10.0,
            "max_value": 11.0,
        }
    ],
    "get_recent_excursions": [
        {
            "run_time": "2026-08-07",
            "lot_id": "LOT-001",
            "process_step": "CMP",
            "equipment_id": "CMP-03",
            "excursion_code": "E001",
            "thickness_nm": 10.0,
            "uniformity_pct": 1.0,
            "defect_density": 0.1,
            "measurement_name": "thickness",
            "measurement_value": 10.0,
            "measurement_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 11.0,
        }
    ],
    "get_defect_pareto": [
        {
            "defect_type": "Scratch",
            "process_steps": "CMP",
            "defect_count": 4,
            "affected_lots": 2,
            "share_pct": 100.0,
        }
    ],
    "search_knowledge": [
        {
            "source_type": "knowledge",
            "reference_id": "KB-PERF-001",
            "status": "Active",
            "authority": 5,
            "title": "CMP-03 Cpk 不合格与化学机械抛光基本原理",
            "section": "Overview",
            "process_steps": "CMP",
            "tags": "CMP,Cpk,抛光",
            "score": -1.0,
            "content": "化学机械抛光结合化学反应与机械作用实现表面平坦化，CMP Cpk 过程控制需要联合量测、异常及传感器证据。",
        }
    ],
}
EXPECTED_TOOLS = {
    "ready_success": [
        "get_process_capability",
        "get_recent_excursions",
        "get_sensor_summary",
        "search_knowledge",
    ],
    "loop_success": ["get_defect_pareto"],
    "knowledge_retrieval_success": ["search_knowledge", "search_knowledge"],
}


class _Audit:
    def __init__(self):
        self.calls = {"socket": 0, "dns": 0, "sqlite": 0}

    def block(self, kind):
        def blocked(*_args, **_kwargs):
            self.calls[kind] += 1
            raise AssertionError(f"performance fixture attempted {kind} access")

        return blocked


def _source_patches(stack, side, business):
    from app.agent_runtime import service

    def rows(tool):
        value = deepcopy(ROWS[tool])
        business.append({"tool": tool, "data": deepcopy(value)})
        return value

    if side == "reference":
        from contextlib import contextmanager
        from app.manufacturing import reports
        from app.knowledge import rag

        class Cursor:
            def __init__(self, tool):
                self.tool = tool

            def fetchall(self):
                return rows(self.tool)

        class Connection:
            def execute(self, sql, _parameters):
                sql = " ".join(sql.lower().split())
                if "from sensor_readings" in sql:
                    return Cursor("get_sensor_summary")
                if "with stats as" in sql:
                    return Cursor("get_process_capability")
                if "from defect_records" in sql:
                    return Cursor("get_defect_pareto")
                if "excursion_code" in sql and "from process_runs" in sql:
                    return Cursor("get_recent_excursions")
                raise AssertionError("unexpected reference report query")

        @contextmanager
        def session():
            yield Connection()

        active_scope = [()]

        class Factory:
            def defect_aliases(self, _principal):
                return {}

            def search(self, _principal, _request):
                return (
                    deepcopy(ROWS["search_knowledge"])
                    if "knowledge" in active_scope[0]
                    else []
                )

        def search(**arguments):
            active_scope[0] = arguments.get("source_types") or (
                "knowledge",
                "case",
                "personal",
            )
            business.append(
                {
                    "tool": "search_knowledge",
                    "data": deepcopy(ROWS["search_knowledge"])
                    if "knowledge" in active_scope[0]
                    else [],
                }
            )
            return rag.search_agent_knowledge(**arguments)

        stack.enter_context(patch.object(reports, "db_session", session))
        stack.enter_context(
            patch.object(rag, "get_factory_search_backend", return_value=Factory())
        )
        stack.enter_context(
            patch.object(rag, "search_personal_knowledge", return_value=[])
        )
        handlers = {
            name: getattr(reports, name.removeprefix("get_"))
            for name in ROWS
            if name != "search_knowledge"
        }
        handlers["search_knowledge"] = search
        stack.enter_context(patch.dict(service.TOOL_HANDLERS, handlers, clear=True))
        return

    from app.agent_runtime.tools.contracts import ToolSource, ToolSourceKind
    from app.tools.knowledge_search.contracts import (
        KnowledgeSearchSnapshot,
        knowledge_scope,
    )
    from app.tools.process_diagnostics.contracts import (
        DiagnosticsSnapshot,
        diagnostics_scope,
    )
    from app.tools.operational_reports.contracts import (
        OperationalReportSnapshot,
        operational_report_scope,
    )

    class Diagnostics:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch(self, query, principal):
            tool = (
                "get_process_capability"
                if query.kind == "capability"
                else "get_sensor_summary"
            )
            return DiagnosticsSnapshot(
                query,
                tuple(rows(tool)),
                ToolSource(
                    "fake:perf/diagnostics",
                    "perf",
                    ToolSourceKind.FAKE,
                    diagnostics_scope(query, principal),
                ),
            )

    class Operational:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch(self, query, principal):
            tool = (
                "get_recent_excursions"
                if query.kind == "excursions"
                else "get_defect_pareto"
            )
            return OperationalReportSnapshot(
                query,
                tuple(rows(tool)),
                ToolSource(
                    "fake:perf/operational",
                    "perf",
                    ToolSourceKind.FAKE,
                    operational_report_scope(query, principal),
                ),
            )

    class Knowledge:
        def fetch(self, query, principal):
            values = (
                rows("search_knowledge") if "knowledge" in query.source_types else []
            )
            if not values:
                business.append({"tool": "search_knowledge", "data": []})
            return KnowledgeSearchSnapshot(
                query,
                principal.tenant_id,
                principal.user_id,
                principal.user_id if "personal" in query.source_types else None,
                {},
                tuple(values),
                (
                    ToolSource(
                        "fake:perf/knowledge",
                        "perf",
                        ToolSourceKind.FAKE,
                        knowledge_scope(principal),
                    ),
                ),
            )

    stack.enter_context(
        patch(
            "app.tools.process_diagnostics.data_source.SQLiteProcessDiagnosticsAdapter",
            Diagnostics,
        )
    )
    stack.enter_context(
        patch(
            "app.tools.operational_reports.data_source.SQLiteOperationalReportsAdapter",
            Operational,
        )
    )
    stack.enter_context(
        patch(
            "app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port",
            lambda **_kwargs: Knowledge(),
        )
    )


def _operation(side, scene, runner=None):
    """Measure only the same whole service boundary, with fixed injected inputs."""
    from contextlib import ExitStack
    from datetime import date
    from types import SimpleNamespace
    from app.agent_runtime import service
    from app.core.identity import Principal, reset_principal, set_principal
    from app.core.settings import get_settings

    settings = SimpleNamespace(**vars(get_settings()).copy())
    settings.model_connection = SimpleNamespace(
        provider="fixture",
        api_key="fixture",
        base_url="https://offline.invalid",
        model="fixture",
    )
    settings.enterprise_default_tenant_id = "demo"
    business, requests, events, usable_items = [], [], [], []
    audit = _Audit()

    async def stream(_client, _endpoint, _headers, payload, _progress, _state):
        requests.append(
            {
                "model": payload["model"],
                "message_count": len(payload["messages"]),
                "tool_count": len(payload.get("tools", [])),
            }
        )
        if scene == "loop_success" and len(requests) == 1:
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "perf-tool",
                            "type": "function",
                            "function": {
                                "name": "get_defect_pareto",
                                "arguments": json.dumps(
                                    {
                                        "start": "2026-08-01",
                                        "end": "2026-08-07",
                                        "process_step": "CMP",
                                        "limit": 1,
                                    }
                                ),
                            },
                        }
                    ],
                },
                {"total_tokens": 1},
                "fixture",
            )
        return (
            {
                "role": "assistant",
                "content": "化学机械抛光需要结合量测与传感器证据进行过程控制。[来源 KB-PERF-001]",
            },
            {"total_tokens": 1},
            "fixture",
        )

    async def progress(event):
        events.append((event.get("event"), event.get("tool")))

    class FixtureDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 7)

    async def measured():
        wall, thread, cpu = (
            time.perf_counter_ns(),
            time.thread_time_ns(),
            time.process_time_ns(),
        )
        result = await service._run_agent_impl(
            QUESTIONS[scene], [], "perf-fixed", progress
        )
        return result, (
            time.perf_counter_ns() - wall,
            time.thread_time_ns() - thread,
            time.process_time_ns() - cpu,
        )

    token = set_principal(Principal("demo", "perf"))
    loop = None
    try:
        if runner is None:
            # Create the loop before the socket guard below.  On Windows the
            # Proactor loop builds its self-pipe through socket.socketpair(),
            # which would otherwise be recorded as forbidden socket access.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(service, "get_settings", return_value=settings)
            )
            stack.enter_context(patch.object(service, "_stream_completion", new=stream))
            stack.enter_context(patch.object(service, "emit"))
            stack.enter_context(patch("app.intent_runtime.routing.date", FixtureDate))
            _source_patches(stack, side, business)
            if side == "reference":
                stack.enter_context(
                    patch("app.knowledge.rag.get_settings", return_value=settings)
                )
            original_usable = service._usable_knowledge_result

            def usable(query, value):
                usable_items.append(deepcopy(value))
                return original_usable(query, value)

            stack.enter_context(
                patch.object(service, "_usable_knowledge_result", usable)
            )
            for target in (
                "socket.create_connection",
                "socket.socket.connect",
                "socket.socket.connect_ex",
            ):
                stack.enter_context(patch(target, audit.block("socket")))
            stack.enter_context(patch("socket.getaddrinfo", audit.block("dns")))
            stack.enter_context(patch("sqlite3.connect", audit.block("sqlite")))
            result, clocks = (
                runner.run(measured(), context=copy_context())
                if runner is not None
                else loop.run_until_complete(measured())
            )
    finally:
        if loop is not None:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        reset_principal(token)
    if any(audit.calls.values()):
        raise AssertionError(f"forbidden source access: {audit.calls}")
    trace = result["tool_trace"]
    if [item["tool"] for item in trace] != EXPECTED_TOOLS[scene]:
        raise AssertionError(f"tool sequence differs: {trace}")
    if any(item["status"] not in {"ok", "success"} for item in trace):
        raise AssertionError(f"fixture tool failed: {trace}")
    for item in trace:
        if item["tool"] == "search_knowledge":
            continue
        arguments = item["arguments"]
        if (
            arguments.get("start") != "2026-08-01"
            or arguments.get("end") != "2026-08-07"
        ):
            raise AssertionError("business date scope differs from the fixed input")
        if arguments.get("process_step") != "CMP":
            raise AssertionError("business process scope differs from the fixed input")
    if len(requests) != (2 if scene == "loop_success" else 1):
        raise AssertionError("model call contract differs")
    if result["loop_guard"]["total_calls"] != len(trace):
        raise AssertionError("guard accounting differs")
    for kind in ("tool_started", "tool_finished"):
        if sum(event == kind for event, _tool in events) != len(trace):
            raise AssertionError(f"tool event delivery differs: {kind}")
    expected_business = [
        {
            "tool": tool,
            "data": (
                []
                if scene == "knowledge_retrieval_success" and index == 0
                else ROWS[tool]
            ),
        }
        for index, tool in enumerate(EXPECTED_TOOLS[scene])
    ]
    if business != expected_business:
        raise AssertionError(f"business source data differs: {business}")
    if side == "current" and any(item.get("tool_version") != "1.0.0" for item in trace):
        raise AssertionError("default call used a compatibility binding")
    if (
        scene == "ready_success"
        and result.get("execution_mode") != "deterministic_ready_plan"
    ):
        raise AssertionError("Ready did not use the deterministic planner")
    if scene == "knowledge_retrieval_success":
        if trace[-1]["rows"] != 1 or not any(
            s.get("reference_id") == "KB-PERF-001" for s in result.get("sources", [])
        ):
            raise AssertionError("scoped knowledge evidence was not adopted")
    return {
        "fixture": f"{side}-whole-service",
        "question": QUESTIONS[scene],
        "business": business,
        "tools": [t["tool"] for t in trace],
        "model_calls": len(requests),
        "guard_calls": result["loop_guard"]["total_calls"],
        "audit": audit.calls,
        "usable_knowledge": usable_items,
        "evidence_validation": result["evidence_validation"],
        "clocks": clocks,
    }


def _current_operation(scene):
    return _operation("current", scene)


def _measure_operation(side, scene, count, runner):
    out = {key: [] for key in _empty(1)}
    proof = None
    for _ in range(count):
        started = time.perf_counter_ns()
        collected = gc.collect()
        cleanup = time.perf_counter_ns() - started
        proof = _operation(side, scene, runner)
        wall, thread, cpu = proof.pop("clocks")
        for key, value in (
            ("wall_samples_ns", wall),
            ("thread_cpu_samples_ns", thread),
            ("process_cpu_samples_ns", cpu),
            ("cleanup_samples_ns", cleanup),
            ("collected_objects", collected),
        ):
            out[key].append(value)
    return out, proof


def _worker(project):
    project = project.resolve(strict=True)
    sys.path.insert(0, str(project))
    persistent_audit = {
        "socket.connect": 0,
        "socket.getaddrinfo": 0,
        "sqlite3.connect": 0,
    }

    def guard(event, _arguments):
        if event in persistent_audit:
            persistent_audit[event] += 1
            raise AssertionError(f"worker attempted forbidden access: {event}")

    sys.addaudithook(guard)
    from app.agent_runtime import service

    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in tuple(sys.modules.items())
        if name.startswith("app.") and getattr(module, "__file__", None)
    }
    if any(not Path(path).is_relative_to(project) for path in origins.values()):
        raise RuntimeError("mixed app import origins")
    active_side, warmed = None, set()
    runner = asyncio.Runner()
    proofs = {}
    for line in sys.stdin:
        request = json.loads(line)
        try:
            command = request.get("command")
            if command == "stop":
                runner.close()
                print('{"ok":true}', flush=True)
                return 0
            if command == "setup":
                active_side = request["side"]
                if active_side not in {"reference", "current"}:
                    raise ValueError("invalid side")
                answer = {
                    "ok": True,
                    "project": str(project),
                    "service_origin": service.__file__,
                    "app_origins": origins,
                }
            elif command == "measure":
                side, scene, count, batch = (
                    request["side"],
                    request["scene"],
                    request["count"],
                    request["batch"],
                )
                if (
                    side != active_side
                    or scene not in SCENES
                    or type(count) is not int
                    or count < 1
                ):
                    raise ValueError("invalid measurement")
                if (scene, batch) not in warmed:
                    for _ in range(WARMUPS):
                        gc.collect()
                        _operation(side, scene, runner)
                    warmed.add((scene, batch))
                measurement, proof = _measure_operation(side, scene, count, runner)
                proofs[scene] = proof
                answer = {"ok": True, "measurement": measurement}
            elif command == "finish":
                all_origins = {
                    name: str(Path(module.__file__).resolve())
                    for name, module in tuple(sys.modules.items())
                    if name.startswith("app.") and getattr(module, "__file__", None)
                }
                if any(
                    not Path(path).is_relative_to(project)
                    for path in all_origins.values()
                ):
                    raise RuntimeError("mixed app import origins after execution")
                if any(persistent_audit.values()):
                    raise AssertionError("worker performed forbidden source access")
                answer = {
                    "ok": True,
                    "proofs": proofs,
                    "warmups": len(warmed) * WARMUPS,
                    "persistent_audit": persistent_audit,
                }
            else:
                raise ValueError("unknown command")
        except Exception as error:
            answer = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        print(json.dumps(answer, ensure_ascii=False), flush=True)
    runner.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--batches", type=int, default=1)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        if args.project_dir is None:
            parser.error("--worker requires --project-dir")
        return _worker(args.project_dir)
    report = run(args.samples, args.batches, args.formal)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
