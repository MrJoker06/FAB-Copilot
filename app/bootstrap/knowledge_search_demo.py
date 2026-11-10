"""Run bounded fake knowledge retrieval through Ready or Loop dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.loop_response import classify_loop_response
from ..agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeEvent,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from ..agent_runtime.tools.dispatch_contracts import PolicyDecision
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.tools.knowledge_search.backend_search import BackendKnowledgeSearchAdapter
from app.demo_data.tool_sources.knowledge_search import FakeKnowledgeSearchAdapter
from app.tools.knowledge_search.binding import create_knowledge_search_binding
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchInput,
    KnowledgeSearchQuery,
    KnowledgeSearchSnapshot,
    PersonalSearchBatch,
    knowledge_owner_id,
    knowledge_scope,
)
from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)
from .agent_assembly import AssemblyError, assemble_agent
from .loop_assembly import bind_loop_run
from .ready_assembly import bind_ready_run

_TOOL = "search_knowledge"


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


@dataclass(slots=True)
class _Events:
    items: list[RuntimeEvent]

    async def emit(self, event: RuntimeEvent) -> None:
        self.items.append(event)


class _Policy:
    def __init__(self, tenant_id: str, user_id: str) -> None:
        self._delegate = DemoToolPolicy(
            frozenset({_TOOL}), frozenset({"analyst"}), tenant_id=tenant_id
        )
        self.user_id = user_id

    def authorize(self, principal: object, name: str, scope: object) -> PolicyDecision:
        if getattr(principal, "user_id", None) != self.user_id:
            return PolicyDecision(
                False, "USER_DENIED", "This principal is not authorized."
            )
        return self._delegate.authorize(principal, name, scope)  # type: ignore[arg-type]


class _ReadyModel:
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        raise AssertionError("Ready execution must not select tools through the model")


@dataclass(slots=True)
class _LoopModel:
    tool: str
    arguments: str
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall("knowledge-tool-1", self.tool, self.arguments),
                )
            )
        if len(self.requests) == 2:
            messages = [
                item
                for item in request.messages
                if item.role == "tool" and item.tool_call_id == "knowledge-tool-1"
            ]
            if len(messages) != 1:
                raise AssertionError("knowledge Loop fixture requires its tool message")
            try:
                payload = json.loads(messages[0].content)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AssertionError(
                    "knowledge Loop fixture requires JSON tool data"
                ) from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("ok"), bool)
                or "data" not in payload
            ):
                raise AssertionError(
                    "knowledge Loop fixture received inconsistent tool data"
                )
            return ModelResponse(
                content="Fixed knowledge retrieval Loop fixture completed."
            )
        raise AssertionError("unexpected knowledge Loop sequence")


class _FixtureFactory:
    def __init__(self, tenant_id: str, candidates: list[dict[str, object]]) -> None:
        self.tenant_id = tenant_id
        self.candidates = deepcopy(candidates)
        self.alias_calls = 0
        self.search_calls = 0

    def defect_aliases(self, principal: _Principal) -> dict[str, tuple[str, ...]]:
        self.alias_calls += 1
        if principal.tenant_id != self.tenant_id:
            raise KnowledgeSearchDataError("fixture tenant mismatch")
        return {"Particles": ("颗粒", "particle")}

    def search(self, principal: _Principal, request: object) -> list[dict[str, object]]:
        self.search_calls += 1
        if principal.tenant_id != self.tenant_id:
            raise KnowledgeSearchDataError("fixture tenant mismatch")
        types = getattr(request, "source_types", ())
        return [deepcopy(row) for row in self.candidates if row["source_type"] in types]


class _FixturePersonal:
    def __init__(self, owner_user_id: str, rows: list[dict[str, object]]) -> None:
        self.owner_user_id = owner_user_id
        self.rows = deepcopy(rows)
        self.calls = 0

    def search(
        self, principal: _Principal, owner_user_id: str, query: str, limit: int
    ) -> PersonalSearchBatch:
        self.calls += 1
        if owner_user_id != self.owner_user_id:
            raise KnowledgeSearchDataError("fixture owner mismatch")
        return PersonalSearchBatch(owner_user_id, tuple(deepcopy(self.rows[:limit])))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--adapter", choices=("fake", "backend"), default="fake")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--source-user-id", default="demo-user")
    parser.add_argument("--default-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default=_TOOL)
    parser.add_argument("--arguments", default='{"query":"LITHO 颗粒"}')
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


def _candidates(owner: str) -> list[dict[str, object]]:
    return [
        {
            "source_type": "knowledge",
            "reference_id": "KB-LITHO-1",
            "status": "Active",
            "title": "LITHO particle guide",
            "section": "Overview",
            "process_steps": "LITHO",
            "authority": 5,
            "tags": "Particles",
            "score": -1.0,
        },
        {
            "source_type": "case",
            "reference_id": "CASE-LITHO-1",
            "case_status": "Validated",
            "title": "Particle recovery",
            "source": "历史案例库",
            "section": "Particle recovery",
            "process_step": "LITHO",
            "equipment_id": "LITHO-01",
            "equipment_family": "LITHO",
            "defect_type": "Particles",
            "root_cause_confidence": 0.9,
            "occurred_date": "2020-01-01",
        },
        {
            "source_type": "personal",
            "reference_id": "PERSONAL-1",
            "owner_user_id": owner,
            "title": "My LITHO particle notes",
            "section": "Notes",
            "process_steps": ["LITHO"],
            "equipment_ids": ["LITHO-01"],
            "tags": ["Particles"],
            "excerpt": "particle notes",
        },
    ]


def _snapshot(
    query: KnowledgeSearchQuery, args: argparse.Namespace
) -> KnowledgeSearchSnapshot:
    principal = _Principal(args.source_tenant_id, args.source_user_id, ("analyst",))
    owner = (
        knowledge_owner_id(principal, args.default_tenant_id)
        if "personal" in query.source_types
        else None
    )
    sources = tuple(
        ToolSource(
            f"fake:knowledge-search/{kind}",
            "fake-knowledge-search",
            ToolSourceKind.FAKE,
            knowledge_scope(principal),
        )
        for kind in query.source_types
    )
    candidates = [
        row
        for row in _candidates(owner or "unused")
        if row["source_type"] in query.source_types
    ]
    return KnowledgeSearchSnapshot(
        query,
        args.source_tenant_id,
        args.source_user_id,
        owner,
        {"Particles": ("颗粒", "particle")},
        tuple(candidates),
        sources,
    )


def _adapter(args: argparse.Namespace, input_value: KnowledgeSearchInput | None):
    if input_value is None:
        if args.adapter == "fake":
            return (
                FakeKnowledgeSearchAdapter(
                    args.source_tenant_id, args.source_user_id, {}
                ),
                "fake",
            )
        principal = _Principal(args.source_tenant_id, args.source_user_id, ("analyst",))
        owner = knowledge_owner_id(principal, args.default_tenant_id)
        return (
            BackendKnowledgeSearchAdapter(
                _FixtureFactory(args.source_tenant_id, []),
                _FixturePersonal(owner, []),
                demo_tenant_id=args.source_tenant_id,
                default_tenant_id=args.default_tenant_id,
            ),
            "backend",
        )
    query = input_value.resolve()
    snapshot = _snapshot(query, args)
    if args.adapter == "fake":
        return FakeKnowledgeSearchAdapter(
            args.source_tenant_id, args.source_user_id, {query: snapshot}
        ), "fake"
    owner = snapshot.owner_user_id or knowledge_owner_id(
        _Principal(args.source_tenant_id, args.source_user_id, ("analyst",)),
        args.default_tenant_id,
    )
    factory = _FixtureFactory(args.source_tenant_id, _candidates(owner))
    personal = _FixturePersonal(
        owner, [row for row in _candidates(owner) if row["source_type"] == "personal"]
    )
    return BackendKnowledgeSearchAdapter(
        factory,
        personal,
        demo_tenant_id=args.source_tenant_id,
        default_tenant_id=args.default_tenant_id,
    ), "backend"


def _plan(tool: str, arguments: dict[str, object], maximum: int) -> ExecutionPlan:
    return ExecutionPlan(
        "knowledge-search-demo",
        "1",
        "demo",
        "ready",
        "",
        "",
        None,
        None,
        AnalysisScopeContract("knowledge", (), (), ()),
        (),
        (
            PlanStep(
                "S01",
                "Knowledge search",
                tool,
                arguments,
                {},
                (),
                (),
                True,
                (),
                100,
                "primary",
            ),
        ),
        PlanBudget(maximum, maximum, 2, 100, {tool: maximum}, 1, 1),
        (),
        (),
    )


def _typed(result: Any) -> dict[str, object]:
    return {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "version": result.tool_version,
        "status": result.status.value,
        "state": result.execution_state.value,
        "execution_state": result.execution_state.value,
        "row_count": result.row_count,
        "data": result.data,
        "error": None
        if result.error is None
        else {
            "code": result.error.code,
            "kind": result.error.kind.value,
            "public_message": result.error.public_message,
        },
    }


def _safe_plan(plan: ExecutionPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "depends_on": list(step.depends_on),
            }
            for step in plan.steps
        ],
        "budget": {
            "max_tool_calls": plan.budget.max_tool_calls,
            "max_rows_per_call": plan.budget.max_rows_per_call,
            "per_tool_limits": dict(plan.budget.per_tool_limits),
        },
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        arguments = json.loads(args.arguments)
        if (
            not isinstance(arguments, dict)
            or args.timeout_ms < 0
            or args.max_tool_calls < 0
        ):
            raise ValueError
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    try:
        input_value = KnowledgeSearchInput.from_arguments(arguments)
    except Exception:  # noqa: BLE001 - invalid raw inputs need no adapter fixture.
        input_value = None
    requested_tool = getattr(args, "tool", _TOOL)
    adapter, adapter_kind = _adapter(args, input_value)
    plan, guard = _plan(requested_tool, arguments, args.max_tool_calls), None
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, args.user_id, (args.role,)),
        f"knowledge-{args.mode}-demo",
        ToolExecutionLimits(
            args.max_tool_calls, 100, time.monotonic() + args.timeout_ms / 1000
        ),
    )
    model: Any = (
        _ReadyModel()
        if args.mode == "ready"
        else _LoopModel(requested_tool, json.dumps(arguments, ensure_ascii=False))
    )
    try:
        definition = AgentDefinition(
            "knowledge-search-demo",
            "1.0.0",
            "analyst",
            "Run approved fake knowledge retrieval.",
            (ComponentReference(_TOOL, "1.0.0"),),
            ComponentReference("knowledge-demo-model", "1.0.0"),
            ComponentReference("knowledge-demo-policy", "1.0.0"),
        )
        projector = ReadyResultPolicy()
        app = assemble_agent(
            definition,
            model=model,
            events=_Events([]),
            bindings=(
                create_knowledge_search_binding(
                    adapter, default_tenant_id=args.default_tenant_id
                ),
            ),
            policy=_Policy(args.source_tenant_id, args.source_user_id),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset({_TOOL}),
            model_policy_ref=ComponentReference("knowledge-demo-model", "1.0.0"),
            policy_ref=ComponentReference("knowledge-demo-policy", "1.0.0"),
        )
        run = app.new_run(context, result_policy=projector)
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    progress: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def notify(_progress: object, event: dict[str, object]) -> None:
        progress.append(
            {key: value for key, value in event.items() if key != "arguments"}
        )

    def emit_event(name: str, run_id: str, **details: object) -> None:
        events.append({"event": name, "run_id": run_id, **details})

    if args.mode == "ready":
        outcome = await execute_dispatched_ready_plan(
            plan,
            guard,
            context.run_id,
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages = []
        final = None
    else:
        first = await run.model_stage(
            call_id="knowledge-model-1",
            messages=(ModelMessage("user", "Run fixed knowledge retrieval."),),
        )
        outcome = await execute_dispatched_loop_round(
            plan,
            guard,
            context.run_id,
            1,
            classify_loop_response(first.value),
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages = list(outcome.tool_messages)
        second = await run.model_stage(
            call_id="knowledge-model-2",
            messages=(
                ModelMessage("user", "Run fixed knowledge retrieval."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage(
                        "tool", item["content"], tool_call_id=item["tool_call_id"]
                    )
                    for item in messages
                ),
            ),
        )
        final = classify_loop_response(second.value).content
    sources = {
        source["source_ref"]: source
        for item in outcome.trace
        for source in item.get("sources", ())
    }
    return {
        "mode": args.mode,
        "adapter_kind": adapter_kind,
        "typed_results": [_typed(item) for item in outcome.tool_results],
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": sources,
        "tool_messages": messages,
        "final_response": final,
        "guard": guard.summary(),
        "model_tool_selection_calls": 0 if args.mode == "ready" else 1,
        "model_response_calls": 0 if args.mode == "ready" else len(model.requests),
        "progress": progress,
        "events": events,
        "plan": _safe_plan(plan),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        payload = asyncio.run(_run(_parser().parse_args(argv)))
    except Exception:  # noqa: BLE001 - standalone demonstration emits safe JSON.
        payload = {"error": "INTERNAL_ERROR"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    return (
        0
        if payload.get("typed_results", [{}])[0].get("status")
        == ToolStatus.SUCCEEDED.value
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
