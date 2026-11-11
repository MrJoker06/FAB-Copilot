"""Deterministic scenario harness for the agent-loop split equivalence golden.

Every collaborator of ``run_agent_loop`` is a recording fake, so one ordered log
captures emitted audit events, progress payloads, model requests, sleeps and
result building exactly as the loop produced them. Volatile timing and
traceback fields are dropped before comparison.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.execution.agent_loop import AgentLoopContext, run_agent_loop
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.evidence.validator import EvidenceObservation
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "agent_loop_split_golden.json"
)
VOLATILE_KEYS = frozenset({"duration_ms", "elapsed_ms", "traceback"})
PROGRESS = "progress-sink"
USAGE = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
SYNC_FIELDS = (
    "evidence_validation",
    "answer_contract",
    "knowledge_fallback",
    "fallback_announced",
    "applied_synthesis_reason",
    "health",
)


def plain(value):
    if isinstance(value, dict):
        return {
            str(key): plain(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "__type__": type(value).__name__,
            **{
                field.name: plain(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, SimpleNamespace):
        return {"__type__": "namespace", **plain(vars(value))}
    if isinstance(value, BaseException):
        return {"__exception__": type(value).__name__, "message": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__object__": type(value).__name__}


class Recorder:
    def __init__(self) -> None:
        self.log: list[dict] = []

    def add(self, kind: str, **payload) -> None:
        self.log.append({"kind": kind, **plain(payload)})


@dataclasses.dataclass
class FakeValidation:
    coverage: dict
    allowed_conclusion_strength: str

    # This is an orchestration-only legacy recorder, not a legal v2 checker
    # result. Its frozen serialization stays unchanged; real report validation
    # and unknown strength rejection are tested against the production boundary.
    @property
    def assessment_status(self):
        return "checked"

    @property
    def evidence_sufficient(self):
        return self.coverage["required_total"] > 0 and self.coverage["required_total"] == self.coverage["required_covered"]

    def to_dict(self) -> dict:
        return {
            "coverage": dict(self.coverage),
            "strength": self.allowed_conclusion_strength,
        }


@dataclasses.dataclass
class FakeContract:
    status: str
    allow_fallback: bool = False
    question: str = ""


class ScriptedSession:
    def __init__(self, recorder: Recorder, script: list) -> None:
        self.recorder = recorder
        self.script = script

    async def stream(self, payload, progress, stream_state):
        self.recorder.add(
            "model_stream",
            payload=payload,
            progress=progress,
            stream_state=stream_state,
        )
        item = self.script.pop(0)
        if callable(item):
            return await item(payload, progress, stream_state)
        if isinstance(item, BaseException):
            raise item
        return item


class ScriptedGateway:
    def __init__(self, recorder: Recorder, script: list) -> None:
        self.recorder = recorder
        self.script = script
        self.opened = 0
        self.closed = 0

    def endpoint_for(self, connection, *, chat_template=None):
        self.recorder.add(
            "endpoint_for", model=connection.model, chat_template=chat_template
        )
        return SimpleNamespace(model=connection.model)

    @asynccontextmanager
    async def open(self, endpoint, *, timeout_seconds):
        self.opened += 1
        self.recorder.add("session_open", timeout_seconds=timeout_seconds)
        try:
            yield ScriptedSession(self.recorder, self.script)
        finally:
            self.closed += 1
            self.recorder.add("session_close")


def text(content: str, usage: dict | None = None, response_id: str = "r-text"):
    return (
        {"role": "assistant", "content": content},
        dict(usage or USAGE),
        response_id,
    )


def calls(*items: tuple, content: str = "", response_id: str = "r-tools"):
    tool_calls = []
    for item in items:
        call_id, name, arguments = item
        call = {"type": "function", "function": {"name": name, "arguments": arguments}}
        if call_id is not None:
            call["id"] = call_id
        tool_calls.append(call)
    return (
        {"role": "assistant", "content": content, "tool_calls": tool_calls},
        dict(USAGE),
        response_id,
    )


def submit(arguments: str, response_id: str = "r-submit"):
    return calls(("submit-1", "submit_analysis", arguments), response_id=response_id)


class Unavailable(ConnectionError):
    pass


def legacy_plan(
    *,
    iterations: int = 3,
    max_tool_calls: int = 8,
    identical: int = 1,
    no_progress: int = 2,
) -> ExecutionPlan:
    step = PlanStep(
        "S01", "alpha", "alpha", {"q": 1}, {}, ("E1",), (), True, (), 10, "primary"
    )
    return ExecutionPlan(
        "legacy-plan",
        "1",
        "test",
        "ready",
        "",
        "analysis",
        None,
        None,
        AnalysisScopeContract("fab", (), (), ()),
        ("E1",),
        (step,),
        PlanBudget(
            4,
            max_tool_calls,
            iterations,
            10,
            {"alpha": 3, "broken": 2, "search_knowledge": 2, "parse_me": 2},
            identical,
            no_progress,
        ),
        (),
        (),
    )


def build_context(
    recorder: Recorder,
    script: list,
    *,
    intent: str = "analysis",
    plan: ExecutionPlan | None = None,
    guard: ToolLoopGuard | None = None,
    answer_status: str = "optional",
    required_total: int = 1,
    knowledge_fallback: dict | None = None,
    knowledge_state: dict | None = None,
    thinking: bool = False,
    provider: str = "test",
    main_recovery_trial: bool = False,
    health_enabled: bool = True,
    max_retries: int = 1,
    correction=None,
    correction_available: bool = True,
    native_fallback=None,
    dispatch_binding=None,
    success_transition: str | None = None,
    retryable=lambda exc: isinstance(exc, ConnectionError),
):
    plan = plan or legacy_plan()
    guard = guard or ToolLoopGuard(plan)
    gateway = ScriptedGateway(recorder, script)
    holder: dict = {}

    async def notify(progress, payload):
        recorder.add("notify", progress=progress, payload=payload)

    async def stream_answer(progress, answer):
        recorder.add("stream_answer", progress=progress, answer=answer)

    def emit(name, run_id, **fields):
        recorder.add("emit", name=name, run_id=run_id, fields=fields)

    def build_result(answer, report):
        context = holder["context"]
        recorder.add(
            "build_result",
            answer=answer,
            report=report,
            synced={name: getattr(context, name) for name in SYNC_FIELDS},
        )
        return {
            "answer": answer,
            "report": report,
            "thinking_policy": {"requested": thinking},
        }

    def record_success(model_id):
        recorder.add("record_model_success", model_id=model_id)
        return {"status": "healthy", "model": model_id}, success_transition

    def record_failure(model_id, category, *, threshold, cooldown_seconds):
        recorder.add(
            "record_model_failure",
            model_id=model_id,
            category=category,
            threshold=threshold,
            cooldown_seconds=cooldown_seconds,
        )
        return {"status": "open", "model": model_id}, "opened"

    def parse_arguments(raw):
        try:
            value = json.loads(raw)
        except Exception as exc:
            return {}, exc
        if not isinstance(value, dict):
            return {}, ValueError("not an object")
        return value, None

    def execute_tool(name, arguments):
        recorder.add("execute_tool", name=name, arguments=arguments)
        if name == "alpha":
            return [{"value": arguments.get("q")}]
        if name == "search_knowledge":
            return [
                {"reference_id": "K1", "ok": True, "title": "usable"},
                {"reference_id": "K2", "ok": False, "title": "noise"},
                "junk",
            ]
        if name == "broken":
            raise RuntimeError("tool exploded")
        return {"echo": arguments}

    def fallback_state(route, observations, sources):
        recorder.add(
            "knowledge_fallback_state",
            intent=route.intent,
            observation_count=len(observations),
            source_ids=sorted(sources),
        )
        return dict(
            knowledge_state or {"used": False, "reason": None, "disclosure": None}
        )

    def validate(plan_value, playbook, observations):
        covered = int(any(item.status == "success" for item in observations))
        recorder.add(
            "validate_evidence",
            plan_id=plan_value.plan_id,
            playbook=playbook,
            observations=observations,
        )
        return FakeValidation(
            {
                "required_total": required_total,
                "required_covered": min(covered, required_total),
            },
            "strong" if covered else "weak",
        )

    def create_contract(
        validation,
        sources,
        *,
        allow_model_knowledge_fallback,
        question,
        resolved_question,
        extra_limitations=(),
    ):
        recorder.add(
            "create_answer_contract",
            validation=validation,
            sources=sources,
            allow=allow_model_knowledge_fallback,
            question=question,
            resolved_question=resolved_question,
        )
        return FakeContract(
            answer_status, allow_model_knowledge_fallback, resolved_question
        )

    def synthesize_legacy(raw, contract, sources, repair_events=None):
        recorder.add(
            "synthesize_legacy",
            raw=raw,
            contract=contract,
            sources=sources,
            repair_events=repair_events,
        )
        return SimpleNamespace(
            answer=f"L:{raw}", report={"kind": "legacy", "repair_events": repair_events}
        )

    def synthesize_submission(
        submission, contract, sources, *, status, repair_events=()
    ):
        recorder.add(
            "synthesize_submission",
            submission=submission,
            contract=contract,
            sources=sources,
            status=status,
            repair_events=repair_events,
        )
        return SimpleNamespace(
            answer="S:" + json.dumps(submission, ensure_ascii=False, sort_keys=True),
            report={"kind": "submission", "status": status},
        )

    def offline_answer(
        question,
        route,
        selection,
        plan_value,
        guard_value,
        resolution,
        *,
        fallback_reason,
    ):
        recorder.add(
            "offline_answer",
            question=question,
            intent=route.intent,
            plan_id=plan_value.plan_id,
            fallback_reason=fallback_reason,
        )
        return {
            "answer": "offline answer",
            "tool_trace": [{"tool": "alpha", "status": "ok", "rows": 1}],
        }

    async def request_correction(
        session, connection, messages, raw, token_cap, remaining, run_id, iteration
    ):
        recorder.add(
            "request_synthesis_correction",
            model=connection.model,
            message_count=len(messages),
            raw=raw,
            token_cap=token_cap,
            remaining_positive=remaining > 0,
            run_id=run_id,
            iteration=iteration,
        )
        return correction

    context = AgentLoopContext(
        settings=SimpleNamespace(
            api_timeout_seconds=7,
            model_max_retries=max_retries,
            model_retry_base_seconds=0.5,
            model_circuit_failure_threshold=3,
            model_circuit_cooldown_seconds=30,
            chat_template_compat=None,
        ),
        connection=SimpleNamespace(
            provider=provider,
            model="m-1",
            base_url="https://offline.invalid",
            api_key="k",
        ),
        intent_route=SimpleNamespace(intent=intent),
        execution_plan=plan,
        selected_playbook="playbook-1",
        loop_guard=guard,
        run_id="run",
        progress=PROGRESS,
        thinking=thinking,
        main_recovery_trial=main_recovery_trial,
        health_enabled=health_enabled,
        selected_model_id="model-a",
        question="原始问题",
        analysis_question="分析问题",
        playbook_selection=SimpleNamespace(name="selection"),
        context_resolution=SimpleNamespace(to_dict=lambda: {"resolved": True}),
        messages=[{"role": "user", "content": "原始问题"}],
        trace=[],
        sources={},
        evidence_observations=[],
        evidence_validation=FakeValidation(
            {"required_total": 0, "required_covered": 0}, "initial"
        ),
        answer_contract=FakeContract(answer_status),
        total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        knowledge_fallback=dict(
            knowledge_fallback or {"used": False, "disclosure": None}
        ),
        fallback_announced=False,
        applied_synthesis_reason=None,
        health={"status": "initial"},
        build_result=build_result,
        notify=notify,
        stream_answer=stream_answer,
        emit_event=emit,
        model_gateway=gateway,
        retryable_model_error=retryable,
        model_error_category=lambda exc: f"category:{type(exc).__name__}",
        model_failure_reason=lambda exc: f"reason:{type(exc).__name__}",
        model_retry_delay=lambda base, attempt, exc: base * attempt,
        record_model_success=record_success,
        record_model_failure=record_failure,
        audit_assistant=lambda assistant: {"audited": assistant.get("content")},
        tools=[
            {"type": "function", "function": {"name": "alpha"}},
            {"type": "function", "function": {"name": "search_knowledge"}},
        ],
        submit_analysis_tool={
            "type": "function",
            "function": {"name": "submit_analysis"},
        },
        parse_tool_arguments=parse_arguments,
        execute_tool=execute_tool,
        usable_knowledge_result=lambda query, item: bool(item.get("ok")),
        normalize_general_knowledge_answer=lambda answer: f"GK:{answer}",
        has_knowledge_fallback_disclosure=lambda answer: answer.startswith(">"),
        knowledge_fallback_state=fallback_state,
        validate_evidence=validate,
        create_answer_contract=create_contract,
        validator_system_message=lambda validation: (
            f"validator:{validation.allowed_conclusion_strength}"
        ),
        synthesizer_system_message=lambda contract: f"synthesizer:{contract.status}",
        synthesize_legacy_answer=synthesize_legacy,
        synthesize_submission=synthesize_submission,
        emit_answer_synthesis=lambda run_id, report: recorder.add(
            "emit_answer_synthesis", run_id=run_id, report=report
        ),
        emit_evidence_validation=lambda run_id, iteration, payload: recorder.add(
            "emit_evidence_validation",
            run_id=run_id,
            iteration=iteration,
            payload=payload,
        ),
        offline_answer=offline_answer,
        evidence_observation_type=EvidenceObservation,
        provider_request_options=lambda provider_name, thinking_value, *_args: (
            {"reasoning_effort": "high"} if thinking_value else {}
        ),
        request_synthesis_correction=request_correction
        if correction_available
        else None,
        dispatch_binding=dispatch_binding,
        native_fallback=native_fallback,
    )
    holder["context"] = context
    return context, gateway


def _native_fallback(recorder: Recorder):
    async def fallback():
        recorder.add("native_fallback")
        return {"answer": "native fallback answer", "tool_trace": []}

    return fallback


def _dispatch_fixture():
    from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
    from tests.test_loop_dispatcher import _binding, _dispatcher, _plan

    plan = _plan()
    projector = ReadyResultPolicy()
    dispatcher = _dispatcher(plan, [{"row": 1}], projector)
    guard, binding = _binding(plan, dispatcher, projector)
    return plan, guard, binding


def _answer_emitted_then_fail(exc: BaseException):
    async def run(_payload, _progress, stream_state):
        stream_state["answer_emitted"] = True
        stream_state["content_chars"] = 5
        raise exc

    return run


def _streamed_text(content: str):
    async def run(_payload, _progress, stream_state):
        stream_state.update(
            answer_emitted=True,
            finish_reason="stop",
            first_content_ms=12,
            max_content_gap_ms=3,
            content_delta_count=4,
            content_chars=len(content),
            reasoning_length=6,
        )
        return text(content, response_id="r-streamed")

    return run


TRUNCATED = '{"conclusion": "partial", "facts": ['
REPAIRED = (
    {
        "role": "assistant",
        "tool_calls": [
            {
                "function": {
                    "name": "submit_analysis",
                    "arguments": '{"conclusion": "fixed"}',
                }
            }
        ],
    },
    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    "r-repair",
    "model_correction_completed",
)
PROSE_CORRECTION = (
    {"role": "assistant", "content": "prose only"},
    {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    None,
    "model_correction_completed",
)


def _scenarios():
    """Return name -> builder(recorder) -> (context, gateway, run kwargs)."""

    def legacy(script, **options):
        def builder(recorder):
            context, gateway = build_context(recorder, list(script), **options)
            return context, gateway, {}

        return builder

    def with_native(script, dispatched=False, **options):
        def builder(recorder):
            extra = {}
            if dispatched:
                plan, guard, binding = _dispatch_fixture()
                extra = {"plan": plan, "guard": guard, "dispatch_binding": binding}
            context, gateway = build_context(
                recorder,
                list(script),
                native_fallback=_native_fallback(recorder),
                **extra,
                **options,
            )
            return context, gateway, {}

        return builder

    def dispatched(script, *, explicit=False, mismatch=False, invalid=False, **options):
        def builder(recorder):
            plan, guard, binding = _dispatch_fixture()
            stored = binding
            if invalid:
                stored = dataclasses.replace(binding, tools_json="{}")
            context, gateway = build_context(
                recorder,
                list(script),
                plan=plan,
                guard=guard,
                dispatch_binding=None if explicit else stored,
                **options,
            )
            kwargs = {}
            if explicit:
                kwargs["dispatch_binding"] = stored
            if mismatch:
                kwargs["dispatch_binding"] = dataclasses.replace(binding)
            return context, gateway, kwargs

        return builder

    tool_round = calls(
        ("c1", "alpha", '{"q": 1}'),
        ("c2", "alpha", '{"q": 1}'),
        ("c3", "broken", "{}"),
        ("c4", "search_knowledge", '{"query": "k"}'),
        ("c5", "submit_analysis", "{}"),
        ("c6", "parse_me", "{bad"),
        (None, "", "{}"),
        response_id="r-round-1",
    )
    dispatched_round = calls(
        ("model-call", "native", '{"value":"expected"}'),
        ("mixed-submit", "submit_analysis", "{}"),
        response_id="r-dispatch-1",
    )
    return {
        "text_answer": legacy([text("最终答案")]),
        "text_answer_empty_content": legacy([text("")]),
        "text_answer_streamed_metrics": legacy(
            [_streamed_text("流式答案")], success_transition="recovered"
        ),
        "general_knowledge_disclosure": legacy(
            [text("通用回答")],
            intent="general_knowledge",
            knowledge_fallback={
                "used": True,
                "disclosure": "知识库无命中",
                "reason": "no_hits",
            },
        ),
        "conversation_without_tools": legacy([text("你好")], intent="conversation"),
        "thinking_deepseek": legacy(
            [text("思考答案")], thinking=True, provider="deepseek"
        ),
        "tool_round_then_synthesis": legacy(
            [tool_round, text("综合答案", response_id="r-round-2")],
            knowledge_state={
                "used": True,
                "reason": "knowledge_empty",
                "disclosure": "通用知识补充",
            },
        ),
        "tool_round_no_progress_then_empty_answer": legacy(
            [
                calls(("n1", "broken", "{}"), response_id="r-np-1"),
                calls(("n2", "broken", '{"again": 1}'), response_id="r-np-2"),
                text("", response_id="r-np-3"),
            ],
            plan=legacy_plan(iterations=4, no_progress=2),
            required_total=0,
        ),
        "iteration_limit": legacy(
            [
                calls(("i1", "alpha", '{"q": 1}'), response_id="r-it-1"),
                calls(("i2", "alpha", '{"q": 2}'), response_id="r-it-2"),
            ],
            plan=legacy_plan(iterations=2),
            required_total=0,
        ),
        "submit_valid_required_contract": legacy(
            [submit('{"conclusion": "ok", "facts": []}')],
            answer_status="required",
            required_total=0,
        ),
        "submit_empty_object": legacy([submit("{}")], required_total=0),
        "submit_non_object_json": legacy(
            [submit("[1, 2]")],
            required_total=0,
            answer_status="required",
            correction=PROSE_CORRECTION,
        ),
        "submit_invalid_repair_accepted": legacy(
            [submit(TRUNCATED)],
            answer_status="required",
            required_total=0,
            correction=REPAIRED,
        ),
        "submit_invalid_repair_rejected_salvaged": legacy(
            [submit(TRUNCATED)],
            answer_status="required",
            required_total=0,
            correction=PROSE_CORRECTION,
        ),
        "submit_invalid_no_token_cap_degraded": legacy(
            [submit("not json at all")],
            answer_status="optional",
            required_total=0,
            correction=REPAIRED,
        ),
        "submit_after_tool_round_required": legacy(
            [
                calls(("a1", "alpha", '{"q": 1}'), response_id="r-sa-1"),
                submit('{"conclusion": "after tools"}', response_id="r-sa-2"),
            ],
            answer_status="required",
        ),
        "retry_503_then_success": legacy(
            [Unavailable("503 upstream"), text("重试后答案")],
            success_transition="recovered",
        ),
        "persistent_failure_local_fallback": legacy(
            [Unavailable("down"), Unavailable("down again")]
        ),
        "persistent_failure_health_disabled": legacy(
            [Unavailable("down"), Unavailable("down again")], health_enabled=False
        ),
        "main_recovery_trial_no_retry_fallback": legacy(
            [Unavailable("down")], main_recovery_trial=True
        ),
        "native_fallback_legacy": with_native(
            [Unavailable("down"), Unavailable("down again")]
        ),
        "native_fallback_dispatched": with_native(
            [Unavailable("down"), Unavailable("down again")], dispatched=True
        ),
        "non_retryable_error_reraised": legacy([ValueError("bad request")]),
        "failure_after_answer_emitted_reraised": legacy(
            [_answer_emitted_then_fail(Unavailable("mid-stream drop"))]
        ),
        "failure_in_second_round_reraised": legacy(
            [
                calls(("f1", "alpha", '{"q": 1}'), response_id="r-f-1"),
                ValueError("late failure"),
            ],
            required_total=0,
        ),
        "cancelled_mid_stream_legacy": legacy(
            [
                calls(("x1", "alpha", '{"q": 1}'), response_id="r-x-1"),
                asyncio.CancelledError(),
            ],
            required_total=0,
        ),
        "dispatched_round_then_text": dispatched(
            [dispatched_round, text("Loop complete.", response_id="r-dispatch-2")]
        ),
        "dispatched_explicit_binding": dispatched(
            [dispatched_round, text("Loop complete.", response_id="r-dispatch-2")],
            explicit=True,
        ),
        "dispatched_submission": dispatched([submit("{}")]),
        "dispatched_invalid_submission_degraded": dispatched(
            [submit("not json")], answer_status="required", correction_available=False
        ),
        "dispatched_text_required_contract": dispatched(
            [text("dispatched text")], answer_status="required"
        ),
        "dispatched_failure_reraised": dispatched(
            [Unavailable("down")], max_retries=0, health_enabled=False
        ),
        "dispatched_failure_health_recorded": dispatched(
            [Unavailable("down"), Unavailable("down")]
        ),
        "dispatched_binding_mismatch": dispatched([], mismatch=True),
        "dispatched_binding_invalid": dispatched([], invalid=True),
        "cancelled_mid_stream_dispatched": dispatched(
            [dispatched_round, asyncio.CancelledError()],
            knowledge_state={"used": True, "reason": "none", "disclosure": "补充"},
        ),
    }


SCENARIO_NAMES = tuple(_scenarios())


def run_scenario(name: str) -> dict:
    recorder = Recorder()
    context, gateway, kwargs = _scenarios()[name](recorder)

    async def fake_sleep(delay, *args, **kwargs):
        recorder.add("sleep", delay=delay)

    outcome: dict
    with patch("asyncio.sleep", new=fake_sleep):
        try:
            result = asyncio.run(run_agent_loop(context, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - CancelledError is part of the contract
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            outcome = {"raised": plain(exc)}
        else:
            outcome = {"result": plain(result)}
    return {
        "log": recorder.log,
        "outcome": outcome,
        "final": plain(
            {
                **{name_: getattr(context, name_) for name_ in SYNC_FIELDS},
                "messages": context.messages,
                "trace": context.trace,
                "sources": context.sources,
                "evidence_observations": context.evidence_observations,
                "total_usage": context.total_usage,
                "guard": context.loop_guard.summary(),
                "remaining_script": len(gateway.script),
                "sessions": [gateway.opened, gateway.closed],
            }
        ),
    }


def record_all() -> dict:
    return {name: run_scenario(name) for name in SCENARIO_NAMES}


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else GOLDEN_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record_all(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
