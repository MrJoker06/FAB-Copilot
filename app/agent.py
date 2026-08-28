from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx

from .agent_tools import TOOL_HANDLERS, TOOLS, search_agent_knowledge
from .agent_runtime import (
    AgentRunLifecycle,
    AgentRunRequest,
    ProgressCallback,
    coordinate_agent_run,
)
from .agent_runtime.preparation import (
    ContextProtocolError as _RuntimeContextProtocolError,
    prepare_agent_run,
)
from .agent_runtime.preparation.context import (
    ContextStageDependencies,
    ResolverDependencies,
    context_json_arguments as _context_json_arguments_runtime,
    context_protocol_correction as _context_protocol_correction_runtime,
    normalized_context_protocol_error as _normalized_context_protocol_error_runtime,
    resolve_conversation_turn as _resolve_conversation_turn_runtime,
    strip_json_fence as _strip_json_fence_runtime,
)
from .agent_runtime.preparation.pipeline import PreparationDependencies
from .agent_runtime.preparation.planning import PlanningDependencies
from .agent_runtime.preparation.routing import RoutingDependencies
from .agent_runtime.execution import (
    AgentLoopContext,
    execute_ready_plan as _execute_ready_plan_runtime,
    ready_step_order as _ready_step_order_runtime,
    run_agent_loop as _run_agent_loop_runtime,
)
from .agent_runtime.retrieval import (
    RetrievalDependencies,
    has_knowledge_fallback_disclosure as _has_knowledge_fallback_disclosure_runtime,
    knowledge_fallback_state as _knowledge_fallback_state_runtime,
    normalize_general_knowledge_answer as _normalize_general_knowledge_answer_runtime,
    prefetch_general_knowledge as _prefetch_general_knowledge_runtime,
    usable_knowledge_result as _usable_knowledge_result_runtime,
)
from .agent_runtime.synthesis import (
    OfflineAnswerDependencies,
    ReadySynthesisDependencies,
    build_ready_model_unavailable_result as _build_ready_model_unavailable_result_runtime,
    build_result as _build_result_runtime,
    offline_answer as _offline_answer_runtime,
    ready_synthesis_fallback as _ready_synthesis_fallback_runtime,
    ready_synthesis_messages as _ready_synthesis_messages_runtime,
    request_ready_synthesis as _request_ready_synthesis_runtime,
    synthesize_ready_assistant as _synthesize_ready_assistant_runtime,
)
from .agent_runtime.telemetry import (
    emit_answer_synthesis as _emit_answer_synthesis_runtime,
    notify as _notify_runtime,
    stream_answer as _stream_answer_runtime,
    trace_reference_counts as _trace_reference_counts_runtime,
)
from .agent_runtime.tools.executor import (
    execute_registered_tool as _execute_registered_tool_runtime,
    parse_tool_arguments as _parse_tool_arguments_runtime,
)
from .answer_synthesizer import (
    MODEL_KNOWLEDGE_DISCLOSURE,
    MODEL_KNOWLEDGE_REF,
    SUBMIT_ANALYSIS_TOOL,
    AnswerSynthesisReport,
    create_answer_contract,
    synthesize_legacy_answer,
    synthesize_submission,
    synthesizer_system_message,
)
from .assistant_capabilities import build_meta_response
from .audit import content_fingerprint, emit
from .config import Settings, get_settings
from .context_resolver import (
    CONTEXTUALIZER_RESPONSE_FORMAT,
    ContextResolution,
    build_contextualizer_messages,
    context_system_message,
    resolve_question_context,
    semantic_context_resolution,
    unresolved_context,
)
from .decision_arbiter import arbitrate_decision, recover_active_flow
from .domain_playbooks import (
    PlaybookSelection,
    playbook_system_message,
    select_playbook,
)
from .evidence_validator import (
    EvidenceObservation,
    validate_evidence,
    validator_system_message,
)
from .intent_router import (
    INTENT_LABELS,
    IntentRoute,
    route_question,
    routing_system_message,
)
from .knowledge_decision import (
    RetrievalDecision,
    assess_retrieval,
    required_scopes,
    retrieval_system_message,
    rewrite_query,
    usable_result,
)
from .loop_guard import ToolLoopGuard
from .model_compatibility import provider_request_options
from .model_health import (
    claim_model_call,
    get_model_health,
    record_model_failure,
    record_model_success,
)
from .model_registry import effective_agent_settings, public_user_model_config
from .model_streaming import (
    audit_assistant,
    model_error_category,
    model_retry_delay,
    retryable_model_error,
    stream_completion,
)
from .planner import (
    ExecutionPlan,
    PlanStep,
    create_execution_plan,
    planner_system_message,
)
from .processes import MANUFACTURING_STEPS
from .reports import equipment_health, fab_overview
from .turn_decision import TurnDecision, build_turn_decision

SYSTEM_PROMPT = f"""你是晶圆厂制造分析 Agent「Fab Copilot」。你的职责是基于工具返回的真实数据回答问题。

当前日期是 {date.today().isoformat()}。用户说“最近N天”时，以这个日期为结束日期准确计算起始日期；未指定时间范围时使用最近90天。

规则：
1. 涉及数字、趋势、设备、批次时必须先调用数据工具，不得猜测。
2. 涉及 SOP、规范、处置建议、工艺解释或历史经验时调用 search_knowledge。该工具会联合检索当前用户个人知识、正式知识与历史案例，引用时必须使用返回的 reference_id，格式为 [来源 PERSONAL-编号]、[来源 KB-数字] 或 [来源 CASE-编号]。引用只放在支撑对应内容的位置，不在答案末尾重复列出或总结来源。
3. 先给结论，再给证据；区分事实、推断和建议。不要宣称相关性就是因果性。
4. 报告百分比时说明时间范围和样本量。若数据不足，明确说明。
5. 不执行写库操作。高风险建议（停机、报废、配方变更）必须要求工程师复核。
6. 回答使用简洁中文，日期使用 YYYY-MM-DD。
7. 本演示系统的制程能力判定统一使用 Cpk 1.33：低于 1.33 为能力不足，1.33 至 1.67 为观察区间，高于或等于 1.67 为稳定；不得自行改写阈值。
8. 历史案例只能用于生成和排序根因假设，不能证明当前问题具有相同根因。必须结合当前制造数据说明案例的相似点、差异和待验证项。
9. 检索结果包含 retrieval.confidence、final_score 和 selection_reason。若所有结果均为 low，必须说明检索证据不足并请求补充站点、设备、缺陷或时间范围；不得用低置信度材料形成确定性结论。
10. 需要调用工具时直接返回 tool_calls，该轮 content 必须为空；只有所有工具调用完成后的最终结论才输出文字。
11. 企业数据工具返回的是可复现模拟数据。get_enterprise_fab_summary 的 aggregation.exact=false 表示确定性投影，不得把 simulated=true 的结果表述为真实生产观测，也不得把 query_enterprise_data 样本外推为全量统计。
12. 只有用户明确询问企业模拟数据、数据规模、数据接口或投影分析时才使用 enterprise 工具；日常设备、批次、良率和异常分析继续使用标准制造数据工具，禁止在同一结论中无说明地混合两套数据口径。
13. 系统会在用户问题前提供 intent_route。它只用于限定分析范围和推荐取证工具，不是制造事实；若标记需要澄清，不得用无范围的工具调用代替澄清。
14. domain_playbook 定义当前领域的证据与回答契约。必须优先覆盖 required=true 的证据；缺失时明确降级结论，不得宣称模板本身就是证据。
15. execution_plan 是当前问题的结构化取证计划。按 depends_on 处理步骤依赖，使用给定参数并覆盖 required=true 的步骤；计划或预算本身不代表工具已经执行成功。
16. runtime_guard 会强制限制总工具数、单工具次数、相同参数重复调用和无进展轮次。进入仅综合模式后不得继续调用工具，必须基于已有证据作答并说明证据缺口。
17. evidence_validation 是对实际工具证据的确定性校验结果。最终措辞不得超过 allowed_conclusion_strength，必须披露缺失、部分覆盖、样本风险、时间或范围偏差、低置信度来源和事实冲突。
18. 对已选择 Domain Playbook 的问题，最终答案必须调用 submit_analysis 提交面向用户的结构化内容；不要输出隐藏思维链。事实必须有合法证据引用，推断、假设、建议和限制必须分开提交。
19. search_knowledge 已执行但没有返回可用内容时，可以用模型通用知识回答一般性技术问题，但必须明确告知用户知识库无结果；不得把模型通用知识表述为厂内 SOP、配方、规格、历史案例或当前生产事实。
20. intent_route.intent=general_knowledge 时，服务端会先分别检索个人知识与工厂知识并提供 knowledge_retrieval 判定。必须遵守该判定：优先使用可用来源，只有明确允许时才补充模型通用知识；不得索要无关的制程、设备、批次或时间范围。
21. intent_route.intent=conversation 时只回答助手身份、能力或问候，不调用知识库、制造数据或模型工具，也不附加知识库无结果声明。

数据库字段提示：
- lots: lot_id, product, technology_nm, route, priority, start_time, complete_time, status, wafer_count, good_wafers, yield_rate(0-1), cycle_time_hours, hold_hours
- process_runs: lot_id, operation_seq, layer_name, process_step, equipment_id, chamber, recipe, run_time, queue_hours, rework_flag, temperature_c, pressure_torr, duration_sec, thickness_nm, uniformity_pct, defect_density, measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl, pass_flag, excursion_code
- equipment_events: equipment_id, event_time, event_type, duration_minutes, severity, reason
- defect_records: lot_id, detected_time, process_step, defect_type, count, disposition
- sensor_readings: lot_id, operation_seq, process_step, equipment_id, chamber, sample_time, signal_name, signal_value, signal_unit, is_missing, is_outlier
- equipment_state_intervals: equipment_id, chamber, start_time, duration_minutes, semi_e10_state, reason
- wafer_maps: lot_id, wafer_no, detected_time, process_step, equipment_id, pattern_class, tested_dies, failed_dies

simulation_scenarios 为评测真值表，Agent 无权访问，不得尝试查询。
"""


async def _notify(progress: ProgressCallback | None, event: dict) -> None:
    await _notify_runtime(progress, event)


async def _stream_answer(progress: ProgressCallback | None, answer: str) -> None:
    await _stream_answer_runtime(
        progress,
        answer,
        notify_callback=_notify,
        yield_control=asyncio.sleep,
    )


def _emit_answer_synthesis(run_id: str, report: AnswerSynthesisReport) -> None:
    _emit_answer_synthesis_runtime(
        run_id,
        report,
        emit_event=emit,
    )


def _trace_reference_counts(result: dict[str, Any]) -> dict[str, int]:
    return _trace_reference_counts_runtime(
        result,
        model_knowledge_ref=MODEL_KNOWLEDGE_REF,
    )


def _offline_answer(
    question: str,
    intent_route: IntentRoute,
    playbook_selection: PlaybookSelection,
    execution_plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    context_resolution: ContextResolution | None = None,
    turn_decision: TurnDecision | None = None,
    runtime_context: dict | None = None,
    run_id: str | None = None,
    fallback_reason: str = "missing_api_key",
) -> dict:
    return _offline_answer_runtime(
        question, intent_route, playbook_selection, execution_plan, loop_guard,
        context_resolution, turn_decision, runtime_context, run_id, fallback_reason,
        deps=OfflineAnswerDependencies(
            validate_evidence=validate_evidence, create_answer_contract=create_answer_contract,
            synthesize_legacy_answer=synthesize_legacy_answer, build_meta_response=build_meta_response,
            fab_overview=fab_overview, equipment_health=equipment_health, emit=emit,
            evidence_observation_type=EvidenceObservation,
        ),
    )


def _routing_progress_message(route: IntentRoute) -> str:
    if route.intent == "unknown":
        return "尚未识别明确分析目标，正在准备澄清问题"
    if route.intent == "ambiguous":
        return "识别到多个分析目标，正在确认优先路径"
    if route.intent == "general_knowledge":
        return "已识别为知识问题，正在检索个人知识与工厂知识"
    if route.intent == "conversation":
        return "已识别为助手对话，正在直接回答"
    scope = "、".join(route.equipment_ids or route.process_steps)
    scope_text = f" · {scope}" if scope else ""
    return f"已识别为{route.intent_label}{scope_text}，正在限定数据范围"


def _playbook_progress_message(selection: PlaybookSelection) -> str:
    if selection.selected_playbook is not None:
        playbook = selection.selected_playbook
        return f"已加载 {playbook.title} · v{playbook.playbook_version}"
    if selection.status == "clarification_required":
        return "存在多个领域模板，正在等待确认主分析目标"
    return "当前问题使用通用分析规则"


def _plan_progress_message(plan: ExecutionPlan) -> str:
    if plan.status == "ready":
        return f"执行计划已生成 · {len(plan.steps)} 步 · 预算 {plan.budget.max_tool_calls} 次工具调用"
    if plan.status == "clarification_required":
        return "执行计划等待补充必要范围"
    return "当前问题不使用领域执行计划"


def _emit_evidence_validation(run_id: str, iteration: int, validation: dict[str, Any]) -> None:
    coverage = validation["coverage"]
    emit(
        "evidence_validation_completed",
        run_id,
        iteration=iteration,
        plan_id=validation["plan_id"],
        required_total=coverage["required_total"],
        required_covered=coverage["required_covered"],
        required_coverage_pct=coverage["required_coverage_pct"],
        risk_count=len(validation["risks"]),
        conflict_count=len(validation["conflicts"]),
        allowed_conclusion_strength=validation["allowed_conclusion_strength"],
    )


def _knowledge_fallback_state(
    intent_route: IntentRoute,
    observations: list[EvidenceObservation],
    sources: dict[str, dict],
) -> dict[str, Any]:
    return _knowledge_fallback_state_runtime(
        intent_route,
        observations,
        sources,
        model_knowledge_disclosure=MODEL_KNOWLEDGE_DISCLOSURE,
    )


def _usable_knowledge_result(query: str, result: dict[str, Any]) -> bool:
    return _usable_knowledge_result_runtime(query, result, usable_result=usable_result)


def _parse_tool_arguments(raw_arguments: Any) -> tuple[dict[str, Any], Exception | None]:
    """Compatibility facade for one model tool argument payload."""
    parsed = _parse_tool_arguments_runtime(raw_arguments)
    return parsed.arguments, parsed.error


def _execute_registered_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Compatibility facade resolving the live mutable tool registry."""
    return _execute_registered_tool_runtime(name, arguments, TOOL_HANDLERS)


def _normalize_general_knowledge_answer(answer: str) -> str:
    return _normalize_general_knowledge_answer_runtime(answer)


def _has_knowledge_fallback_disclosure(answer: str) -> bool:
    return _has_knowledge_fallback_disclosure_runtime(answer)


def _ready_step_order(plan: ExecutionPlan) -> tuple[PlanStep, ...]:
    """Compatibility facade for the extracted ready-plan ordering stage."""
    return _ready_step_order_runtime(plan)


async def _execute_ready_plan(
    plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    run_id: str,
    progress: ProgressCallback | None,
) -> tuple[list[dict[str, Any]], list[EvidenceObservation], dict[str, dict[str, Any]]]:
    """Compatibility facade using current module globals as live dependencies."""
    return await _execute_ready_plan_runtime(
        plan, loop_guard, run_id, progress,
        notify=_notify,
        emit_event=emit,
        execute_tool=_execute_registered_tool,
        usable_knowledge_result=_usable_knowledge_result,
    )


def _ready_synthesis_dependencies() -> ReadySynthesisDependencies:
    """Resolve synthesis facades at call time so legacy patches remain live."""
    return ReadySynthesisDependencies(
        submit_analysis_tool=SUBMIT_ANALYSIS_TOOL,
        synthesizer_system_message=synthesizer_system_message,
        synthesize_legacy_answer=synthesize_legacy_answer,
        synthesize_submission=synthesize_submission,
        ready_synthesis_fallback=_ready_synthesis_fallback,
        provider_request_options=provider_request_options,
        stream_completion=_stream_completion,
        retryable_model_error=_retryable_model_error,
        model_failure_reason=_model_failure_reason,
        model_retry_delay=_model_retry_delay,
        audit_assistant=_audit_assistant,
        emit=emit,
        sleep=asyncio.sleep,
        perf_counter=time.perf_counter,
    )


def _ready_synthesis_messages(
    question: str,
    plan: ExecutionPlan,
    validation: Any,
    contract: Any,
    observations: list[EvidenceObservation],
) -> list[dict[str, str]]:
    return _ready_synthesis_messages_runtime(
        question, plan, validation, contract, observations, deps=_ready_synthesis_dependencies()
    )


def _ready_synthesis_fallback(
    validation: Any,
    contract: Any,
    observations: list[EvidenceObservation],
    reason: str,
):
    return _ready_synthesis_fallback_runtime(
        validation, contract, observations, reason, deps=_ready_synthesis_dependencies()
    )


async def _request_ready_synthesis(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict[str, str],
    connection: Any,
    settings: Any,
    messages: list[dict[str, str]],
    run_id: str,
    thinking: bool,
    retry_budget: int,
) -> tuple[dict[str, Any], dict[str, Any], str | None, dict[str, Any]]:
    """Compatibility facade for the extracted synthesis-only model request."""
    return await _request_ready_synthesis_runtime(
        client, endpoint, headers, connection, settings, messages, run_id, thinking, retry_budget,
        deps=_ready_synthesis_dependencies(),
    )


def _synthesize_ready_assistant(
    assistant: dict[str, Any],
    contract: Any,
    sources: list[dict],
    validation: Any,
    observations: list[EvidenceObservation],
    run_id: str,
) -> Any:
    """Compatibility facade for final Ready assistant parsing."""
    return _synthesize_ready_assistant_runtime(
        assistant,
        contract,
        sources,
        validation,
        observations,
        run_id,
        deps=_ready_synthesis_dependencies(),
    )


async def _prefetch_general_knowledge(
    question: str,
    run_id: str,
    loop_guard: ToolLoopGuard,
    observations: list[EvidenceObservation],
    trace: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    progress: ProgressCallback | None,
) -> RetrievalDecision:
    return await _prefetch_general_knowledge_runtime(
        question,
        run_id,
        loop_guard,
        observations,
        trace,
        sources,
        progress,
        deps=RetrievalDependencies(
            required_scopes=required_scopes,
            rewrite_query=rewrite_query,
            assess_retrieval=assess_retrieval,
            execute_tool=_execute_registered_tool,
            usable_result=_usable_knowledge_result,
            notify=_notify,
            emit=emit,
            perf_counter=time.perf_counter,
        ),
    )


async def _stream_completion(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict,
    request_payload: dict,
    progress: ProgressCallback | None,
    stream_state: dict[str, Any] | None = None,
) -> tuple[dict, dict, str | None]:
    return await stream_completion(
        client,
        endpoint,
        headers,
        request_payload,
        progress,
        stream_state,
        notify=_notify,
        disclosure_checker=_has_knowledge_fallback_disclosure,
    )


def _audit_assistant(assistant: dict | None) -> dict:
    return audit_assistant(assistant)


def _retryable_model_error(exc: Exception) -> bool:
    return retryable_model_error(exc)


def _model_error_category(exc: Exception) -> str:
    return model_error_category(exc)


def _model_failure_reason(exc: Exception) -> str:
    """Classify audits without presenting local protocol faults as network failures."""
    if isinstance(exc, ContextProtocolError):
        return exc.code
    if _retryable_model_error(exc):
        return _model_error_category(exc)
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return "protocol_error"
    return "internal_error"


def _model_retry_delay(base_seconds: float, retry_number: int, exc: Exception) -> float:
    return model_retry_delay(base_seconds, retry_number, exc)


ContextProtocolError = _RuntimeContextProtocolError

def _strip_json_fence(content: str) -> str:
    return _strip_json_fence_runtime(content)


def _context_json_arguments(assistant: dict) -> dict:
    return _context_json_arguments_runtime(assistant, protocol_error=ContextProtocolError)


def _context_protocol_correction(error: ContextProtocolError) -> dict:
    return _context_protocol_correction_runtime(error)


def _normalized_context_protocol_error(error: ContextProtocolError, finish_reason: str | None) -> ContextProtocolError:
    return _normalized_context_protocol_error_runtime(error, finish_reason)


async def _resolve_conversation_turn(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: ProgressCallback | None,
    direct_route: IntentRoute | None = None,
    thinking: bool = False,
    health_model_id: str | None = None,
    health_recovery_trial: bool = False,
) -> tuple[ContextResolution, dict]:
    return await _resolve_conversation_turn_runtime(
        question,
        history,
        settings,
        run_id,
        progress,
        direct_route,
        thinking,
        health_model_id,
        health_recovery_trial,
        deps=_agent_preparation_dependencies().context.resolver,
    )


def _agent_preparation_dependencies() -> PreparationDependencies:
    """Resolve compatibility dependencies when a run starts, not at import time."""
    return PreparationDependencies(
        context=ContextStageDependencies(
            resolver=ResolverDependencies(
                resolve_question_context=resolve_question_context,
                unresolved_context=unresolved_context,
                build_messages=build_contextualizer_messages,
                response_format=CONTEXTUALIZER_RESPONSE_FORMAT,
                provider_options=provider_request_options,
                stream_completion=_stream_completion,
                semantic_resolution=semantic_context_resolution,
                notify=_notify,
                emit=emit,
                perf_counter=time.perf_counter,
                async_client=httpx.AsyncClient,
                timeout=asyncio.timeout,
                sleep=asyncio.sleep,
                failure_reason=_model_failure_reason,
                retryable_error=_retryable_model_error,
                error_category=_model_error_category,
                retry_delay=_model_retry_delay,
                audit_assistant=_audit_assistant,
                record_failure=record_model_failure,
                record_success=record_model_success,
                content_fingerprint=content_fingerprint,
            ),
            notify=_notify,
            emit=emit,
            perf_counter=time.perf_counter,
            isinstance_settings=lambda value: isinstance(value, Settings),
            public_model_config=public_user_model_config,
            route_question=route_question,
            get_model_health=get_model_health,
            claim_model_call=claim_model_call,
            resolve_turn=_resolve_conversation_turn,
        ),
        routing=RoutingDependencies(
            route_question=route_question,
            recover_active_flow=recover_active_flow,
            arbitrate_decision=arbitrate_decision,
            build_turn_decision=build_turn_decision,
            intent_labels=set(INTENT_LABELS),
            notify=_notify,
            emit=emit,
            perf_counter=time.perf_counter,
            progress_message=_routing_progress_message,
        ),
        planning=PlanningDependencies(
            select_playbook=select_playbook,
            create_execution_plan=create_execution_plan,
            notify=_notify,
            emit=emit,
            playbook_message=_playbook_progress_message,
            plan_message=_plan_progress_message,
        ),
    )


async def _run_agent_impl(
    question: str,
    history: list[dict] | None,
    run_id: str,
    progress: ProgressCallback | None = None,
    thinking: bool = False,
) -> dict:
    context_started = time.perf_counter()
    settings = effective_agent_settings(get_settings())
    preparation = await prepare_agent_run(
        question,
        history,
        settings,
        run_id,
        progress,
        thinking,
        context_started,
        deps=_agent_preparation_dependencies(),
    )
    context_resolution = preparation.context.resolution
    context_usage = preparation.context.usage
    health_enabled = isinstance(settings, Settings)
    selected_model_id = preparation.context.selected_model_id
    analysis_question = preparation.routing.analysis_question
    intent_route = preparation.routing.intent_route
    turn_decision = preparation.routing.turn_decision
    route_payload = intent_route.to_dict()
    playbook_selection = preparation.planning.playbook_selection
    playbook_payload = preparation.planning.playbook_payload
    selected_playbook = playbook_selection.selected_playbook
    execution_plan = preparation.planning.execution_plan
    plan_payload = preparation.planning.plan_payload
    thinking_answer_effective = False
    loop_guard = ToolLoopGuard(execution_plan)
    evidence_observations: list[EvidenceObservation] = []
    evidence_validation = validate_evidence(execution_plan, selected_playbook, evidence_observations)
    answer_contract = create_answer_contract(evidence_validation)
    emit(
        "loop_guard_initialized",
        run_id,
        plan_id=execution_plan.plan_id,
        max_tool_calls=execution_plan.budget.max_tool_calls,
        max_model_iterations=execution_plan.budget.max_model_iterations,
        per_tool_limits=execution_plan.budget.per_tool_limits,
        max_identical_parameter_calls=execution_plan.budget.max_identical_parameter_calls,
        max_no_progress_rounds=execution_plan.budget.max_no_progress_rounds,
    )
    if execution_plan.status == "clarification_required":
        await _notify(progress, {
            "event": "stage",
            "stage": "clarification",
            "message": "当前分析目标仍不明确，正在整理需要补充的信息",
        })
        result = _offline_answer(
            analysis_question,
            intent_route,
            playbook_selection,
            execution_plan,
            loop_guard,
            context_resolution,
            turn_decision,
            {"thinking_requested": thinking, "previous_metadata": next((item.get("metadata") for item in reversed(history or []) if item.get("role") == "assistant" and isinstance(item.get("metadata"), dict)), None)},
            run_id,
        )
        result["mode"] = "clarification"
        result["model"] = settings.model_connection.model if context_usage else "deterministic-router"
        result["usage"] = context_usage
        result["context_resolution"] = context_resolution.to_dict()
        _emit_evidence_validation(run_id, 1, result["evidence_validation"])
        emit(
            "answer_synthesis_completed",
            run_id,
            plan_id=result["answer_synthesis"]["plan_id"],
            status=result["answer_synthesis"]["status"],
            allowed_conclusion_strength=result["answer_synthesis"]["allowed_conclusion_strength"],
            source_count=0,
            invalid_source_count=0,
            moved_claims=0,
            wording_adjustment_count=0,
        )
        await _stream_answer(progress, result["answer"])
        return result
    if intent_route.intent == "conversation":
        result = _offline_answer(
            analysis_question,
            intent_route,
            playbook_selection,
            execution_plan,
            loop_guard,
            context_resolution,
            turn_decision,
            {"thinking_requested": thinking, "previous_metadata": next((item.get("metadata") for item in reversed(history or []) if item.get("role") == "assistant" and isinstance(item.get("metadata"), dict)), None)},
            run_id,
        )
        result["model"] = settings.model_connection.model if context_usage else "deterministic-router"
        result["usage"] = context_usage
        result["context_resolution"] = context_resolution.to_dict()
        result["knowledge_fallback"] = {"used": False, "reason": None, "disclosure": None}
        result["retrieval_decision"] = {
            "state": "NOT_APPLICABLE",
            "reason": None,
            "attempted_scopes": [],
            "attempts": [],
            "selected_reference_ids": [],
            "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
            "rewritten_query": None,
            "assumptions": [],
            "model_knowledge_allowed": False,
            "disclosure": None,
        }
        _emit_evidence_validation(run_id, 1, result["evidence_validation"])
        emit(
            "answer_synthesis_completed",
            run_id,
            plan_id=result["answer_synthesis"]["plan_id"],
            status=result["answer_synthesis"]["status"],
            allowed_conclusion_strength=result["answer_synthesis"]["allowed_conclusion_strength"],
            source_count=0,
            invalid_source_count=0,
            moved_claims=0,
            wording_adjustment_count=0,
        )
        await _stream_answer(progress, result["answer"])
        return result
    connection = settings.model_connection
    # Contextualization may have exhausted the final retry budget and opened the
    # circuit; do not start the main completion in that case.
    model_health = get_model_health(selected_model_id) if health_enabled else {"status": "unknown"}
    health_allowed = True
    main_recovery_trial = False
    if connection.api_key and health_enabled:
        health_allowed, model_health, transition = claim_model_call(
            selected_model_id,
            cooldown_seconds=settings.model_circuit_cooldown_seconds,
            lease_seconds=settings.model_circuit_recovery_lease_seconds,
        )
        if transition:
            main_recovery_trial = transition in {"recovery_started", "recovery_reclaimed"}
            emit("model_circuit_recovery_started", run_id, model_id=selected_model_id, health=model_health)
    if not connection.api_key or not health_allowed:
        await _notify(progress, {"event": "stage", "stage": "planning", "message": "正在使用本地规则规划分析路径"})
        fallback_reason = "missing_api_key" if not connection.api_key else "circuit_open"
        if fallback_reason == "circuit_open":
            emit("model_local_fallback_activated", run_id, model_id=selected_model_id, reason=fallback_reason, health=model_health)
        if execution_plan.status == "ready":
            await _notify(progress, {
                "event": "stage",
                "stage": "tools",
                "message": f"正在按依赖顺序执行 {len(execution_plan.steps)} 个已批准步骤",
                "execution_mode": "deterministic",
            })
            trace, evidence_observations, sources = await _execute_ready_plan(
                execution_plan,
                loop_guard,
                run_id,
                progress,
            )
            evidence_validation = validate_evidence(
                execution_plan,
                selected_playbook,
                evidence_observations,
            )
            answer_contract = create_answer_contract(
                evidence_validation,
                list(sources.values()),
            )
            synthesis = _ready_synthesis_fallback(
                evidence_validation,
                answer_contract,
                evidence_observations,
                "模型未配置或模型熔断器当前阻止综合请求",
            )
            _emit_evidence_validation(run_id, 1, evidence_validation.to_dict())
            _emit_answer_synthesis(run_id, synthesis.report)
            await _notify(progress, {
                "event": "stage",
                "stage": "validation",
                "message": (
                    "证据校验完成 · "
                    f"必需证据 {evidence_validation.coverage['required_covered']}/"
                    f"{evidence_validation.coverage['required_total']} · "
                    f"结论强度 {evidence_validation.allowed_conclusion_strength}"
                ),
                "validation": evidence_validation.to_dict(),
                "execution_mode": "deterministic",
            })
            await _notify(progress, {
                "event": "stage",
                "stage": "synthesis",
                "message": "模型综合不可用，正在输出证据安全的降级说明",
                "execution_mode": "deterministic_fallback",
            })
            await _stream_answer(progress, synthesis.answer)
            return _build_ready_model_unavailable_result_runtime(
                synthesis.answer,
                synthesis.report,
                trace=trace,
                route_payload=route_payload,
                playbook_payload=playbook_payload,
                plan_payload=plan_payload,
                loop_guard=loop_guard,
                evidence_validation=evidence_validation,
                answer_contract=answer_contract,
                context_resolution=context_resolution,
                thinking=thinking,
                turn_decision=turn_decision,
                selected_model_id=selected_model_id,
                fallback_reason=fallback_reason,
                model_health=model_health,
                usage=context_usage,
            )
        result = _offline_answer(analysis_question, intent_route, playbook_selection, execution_plan, loop_guard, fallback_reason=fallback_reason)
        _emit_evidence_validation(run_id, 1, result["evidence_validation"])
        emit(
            "answer_synthesis_completed",
            run_id,
            plan_id=result["answer_synthesis"]["plan_id"],
            status=result["answer_synthesis"]["status"],
            allowed_conclusion_strength=result["answer_synthesis"]["allowed_conclusion_strength"],
            source_count=len(result["answer_synthesis"]["source_refs"]),
            invalid_source_count=len(result["answer_synthesis"]["invalid_source_refs"]),
            moved_claims=result["answer_synthesis"]["moved_claims"],
            wording_adjustment_count=len(result["answer_synthesis"]["wording_adjustments"]),
        )
        for item in result["tool_trace"]:
            await _notify(progress, {"event": "tool_started", "tool": item["tool"], "arguments": {}})
            await _notify(progress, {"event": "tool_finished", **item})
        await _notify(progress, {
            "event": "stage",
            "stage": "validation",
            "message": (
                "证据校验完成 · "
                f"必需证据 {result['evidence_validation']['coverage']['required_covered']}/"
                f"{result['evidence_validation']['coverage']['required_total']} · "
                f"结论强度 {result['evidence_validation']['allowed_conclusion_strength']}"
            ),
            "validation": result["evidence_validation"],
        })
        await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "正在汇总本地分析结果"})
        await _stream_answer(progress, result["answer"])
        result["model"] = "local-rules"
        result["model_health"] = {"requested_model_id": selected_model_id, "fallback_reason": fallback_reason, **model_health}
        result["usage"] = {}
        result["context_resolution"] = context_resolution.to_dict()
        return result

    _emit_evidence_validation(run_id, 0, evidence_validation.to_dict())

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context_resolution.applied:
        messages.append({"role": "system", "content": context_system_message(context_resolution)})
    messages.extend([
        {"role": "system", "content": routing_system_message(intent_route)},
        {"role": "system", "content": playbook_system_message(playbook_selection)},
        {"role": "system", "content": planner_system_message(execution_plan)},
        {"role": "system", "content": validator_system_message(evidence_validation)},
        {"role": "system", "content": synthesizer_system_message(answer_contract)},
    ])
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:4000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    trace: list[dict] = []
    sources: dict[str, dict] = {}
    endpoint = f"{connection.base_url}/chat/completions"
    total_usage = {
        key: int(context_usage.get(key, 0) or 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    applied_synthesis_reason: str | None = None
    health = model_health
    knowledge_fallback = {"used": False, "reason": None, "disclosure": None}
    fallback_announced = False
    retrieval_decision_payload: dict[str, Any] = {
        "state": "NOT_APPLICABLE",
        "reason": None,
        "attempted_scopes": [],
        "attempts": [],
        "selected_reference_ids": [],
        "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
        "rewritten_query": None,
        "assumptions": [],
        "model_knowledge_allowed": False,
        "disclosure": None,
    }

    if intent_route.intent == "general_knowledge":
        retrieval_decision = await _prefetch_general_knowledge(
            analysis_question,
            run_id,
            loop_guard,
            evidence_observations,
            trace,
            sources,
            progress,
        )
        retrieval_decision_payload = retrieval_decision.to_dict()
        knowledge_fallback = {
            "used": retrieval_decision.model_knowledge_allowed,
            "reason": retrieval_decision.reason if retrieval_decision.model_knowledge_allowed else None,
            "disclosure": retrieval_decision.disclosure,
        }
        evidence_validation = validate_evidence(execution_plan, selected_playbook, evidence_observations)
        answer_contract = create_answer_contract(
            evidence_validation,
            list(sources.values()),
            allow_model_knowledge_fallback=retrieval_decision.model_knowledge_allowed,
        )
        messages.extend([
            {"role": "system", "content": retrieval_system_message(retrieval_decision, list(sources.values()))},
            {"role": "system", "content": synthesizer_system_message(answer_contract)},
            {
                "role": "system",
                "content": (
                    "当前是知识型问题的最终回答阶段。只输出面向用户的中文 Markdown 正文；"
                    "不得输出 JSON、tool_calls、函数参数或 submit_analysis，且不得请求生产范围。"
                ),
            },
        ])
        if knowledge_fallback["used"]:
            fallback_announced = True
            emit(
                "knowledge_fallback_enabled",
                run_id,
                reason=knowledge_fallback["reason"],
                model=connection.model,
                retrieval_state=retrieval_decision.state,
            )
            await _notify(progress, {
                "event": "stage",
                "stage": "knowledge_fallback",
                "message": (
                    "知识库仅覆盖部分内容，正在使用模型通用知识补充"
                    if retrieval_decision.state == "HYBRID_GENERAL_SUPPLEMENT"
                    else "个人知识库和工厂知识库均未检索到可用内容，正在使用模型通用知识回答"
                ),
                "knowledge_fallback": knowledge_fallback,
            })

    def build_result(answer: str, synthesis_report: AnswerSynthesisReport) -> dict:
        return _build_result_runtime(
            answer, synthesis_report, trace=trace, sources=sources, intent_route=intent_route,
            connection=connection, total_usage=total_usage, route_payload=route_payload,
            playbook_payload=playbook_payload, plan_payload=plan_payload, loop_guard=loop_guard,
            evidence_validation=evidence_validation, answer_contract=answer_contract,
            context_resolution=context_resolution, knowledge_fallback=knowledge_fallback,
            retrieval_decision_payload=retrieval_decision_payload, thinking=thinking,
            thinking_answer_effective=thinking_answer_effective, turn_decision=turn_decision,
        )

    if execution_plan.status == "ready":
        await _notify(progress, {
            "event": "stage",
            "stage": "tools",
            "message": f"正在按依赖顺序执行 {len(execution_plan.steps)} 个已批准步骤",
            "execution_mode": "deterministic",
        })
        trace, evidence_observations, sources = await _execute_ready_plan(
            execution_plan,
            loop_guard,
            run_id,
            progress,
        )
        evidence_validation = validate_evidence(
            execution_plan,
            selected_playbook,
            evidence_observations,
        )
        knowledge_fallback = _knowledge_fallback_state(
            intent_route,
            evidence_observations,
            sources,
        )
        answer_contract = create_answer_contract(
            evidence_validation,
            list(sources.values()),
            allow_model_knowledge_fallback=knowledge_fallback["used"],
        )
        _emit_evidence_validation(run_id, 1, evidence_validation.to_dict())
        await _notify(progress, {
            "event": "stage",
            "stage": "validation",
            "message": (
                "证据校验完成 · "
                f"必需证据 {evidence_validation.coverage['required_covered']}/"
                f"{evidence_validation.coverage['required_total']} · "
                f"结论强度 {evidence_validation.allowed_conclusion_strength}"
            ),
            "validation": evidence_validation.to_dict(),
            "execution_mode": "deterministic",
        })
        if knowledge_fallback["used"]:
            fallback_announced = True
            emit(
                "knowledge_fallback_enabled",
                run_id,
                reason=knowledge_fallback["reason"],
                model=connection.model,
            )
            await _notify(progress, {
                "event": "stage",
                "stage": "knowledge_fallback",
                "message": "知识库未检索到相关内容，正在使用模型通用知识补充回答",
                "knowledge_fallback": knowledge_fallback,
            })
        await _notify(progress, {
            "event": "stage",
            "stage": "synthesis",
            "message": "计划工具已执行完毕，正在基于已验证证据生成结论",
            "execution_mode": "synthesis_only",
        })
        messages = _ready_synthesis_messages(
            analysis_question,
            execution_plan,
            evidence_validation,
            answer_contract,
            evidence_observations,
        )
        retry_budget = 0 if main_recovery_trial else settings.model_max_retries
        try:
            async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
                assistant, usage, _, _ = await _request_ready_synthesis(
                    client,
                    endpoint,
                    {
                        "Authorization": f"Bearer {connection.api_key}",
                        "Content-Type": "application/json",
                    },
                    connection,
                    settings,
                    messages,
                    run_id,
                    thinking,
                    retry_budget,
                )
            for key in total_usage:
                total_usage[key] += int(usage.get(key, 0) or 0)
            thinking_answer_effective = thinking_answer_effective or thinking
            if health_enabled:
                health, transition = record_model_success(selected_model_id)
                if transition:
                    emit("model_circuit_recovered", run_id, model_id=selected_model_id, health=health)

            synthesis = _synthesize_ready_assistant(
                assistant,
                answer_contract,
                list(sources.values()),
                evidence_validation,
                evidence_observations,
                run_id,
            )
        except Exception as exc:
            if _retryable_model_error(exc) and health_enabled:
                health, transition = record_model_failure(
                    selected_model_id,
                    _model_error_category(exc),
                    threshold=settings.model_circuit_failure_threshold,
                    cooldown_seconds=settings.model_circuit_cooldown_seconds,
                )
                emit(
                    "model_health_failure_recorded",
                    run_id,
                    model_id=selected_model_id,
                    health=health,
                    transition=transition,
                )
            emit(
                "model_local_fallback_activated",
                run_id,
                model_id=selected_model_id,
                reason="ready_synthesis_unavailable",
                health=health,
            )
            synthesis = _ready_synthesis_fallback(
                evidence_validation,
                answer_contract,
                evidence_observations,
                "模型综合服务暂时不可用",
            )

        _emit_answer_synthesis(run_id, synthesis.report)
        await _stream_answer(progress, synthesis.answer)
        result = build_result(synthesis.answer, synthesis.report)
        result["execution_mode"] = "deterministic_ready_plan"
        result["model_tool_selection_calls"] = 0
        if synthesis.report.status != "structured":
            result["mode"] = "deterministic-fallback"
        return result

    return await _run_agent_loop_runtime(
        AgentLoopContext(
            settings=settings, connection=connection, intent_route=intent_route,
            execution_plan=execution_plan, selected_playbook=selected_playbook,
            loop_guard=loop_guard, run_id=run_id, progress=progress, thinking=thinking,
            main_recovery_trial=main_recovery_trial, health_enabled=health_enabled,
            selected_model_id=selected_model_id, analysis_question=analysis_question,
            playbook_selection=playbook_selection, context_resolution=context_resolution,
            messages=messages, trace=trace, sources=sources,
            evidence_observations=evidence_observations, evidence_validation=evidence_validation,
            answer_contract=answer_contract, total_usage=total_usage,
            knowledge_fallback=knowledge_fallback, fallback_announced=fallback_announced,
            applied_synthesis_reason=applied_synthesis_reason, health=health,
            build_result=build_result, notify=_notify, stream_answer=_stream_answer,
            emit_event=emit, stream_completion=_stream_completion,
            retryable_model_error=_retryable_model_error, model_error_category=_model_error_category,
            model_failure_reason=_model_failure_reason,
            model_retry_delay=_model_retry_delay, record_model_success=record_model_success,
            record_model_failure=record_model_failure, audit_assistant=_audit_assistant,
            tools=TOOLS, submit_analysis_tool=SUBMIT_ANALYSIS_TOOL,
            parse_tool_arguments=_parse_tool_arguments, execute_tool=_execute_registered_tool,
            usable_knowledge_result=_usable_knowledge_result,
            normalize_general_knowledge_answer=_normalize_general_knowledge_answer,
            has_knowledge_fallback_disclosure=_has_knowledge_fallback_disclosure,
            knowledge_fallback_state=_knowledge_fallback_state, validate_evidence=validate_evidence,
            create_answer_contract=create_answer_contract,
            validator_system_message=validator_system_message,
            synthesizer_system_message=synthesizer_system_message,
            synthesize_legacy_answer=synthesize_legacy_answer,
            synthesize_submission=synthesize_submission,
            emit_answer_synthesis=_emit_answer_synthesis,
            emit_evidence_validation=_emit_evidence_validation, offline_answer=_offline_answer,
            evidence_observation_type=EvidenceObservation,
            provider_request_options=provider_request_options,
        )
    )


async def run_agent(
    question: str,
    history: list[dict] | None = None,
    progress: ProgressCallback | None = None,
    *,
    thinking: bool = False,
    session_id: str | None = None,
    user_message_id: int | None = None,
) -> dict:
    run_id = str(uuid.uuid4())
    lifecycle = AgentRunLifecycle(
        started_monotonic=time.perf_counter(),
        started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )

    async def tracked_progress(event: dict) -> None:
        if event.get("event") == "answer_delta" and lifecycle.first_answer_delta_monotonic is None:
            lifecycle.observe_progress(event, time.perf_counter())
        await _notify(progress, event)
    emit(
        "agent_run_started",
        run_id,
        question_length=len(question),
        question_fingerprint=content_fingerprint(question),
        history_messages=len(history or []),
        session_id=session_id,
        user_message_id=user_message_id,
        thinking_policy={"requested": thinking, "context_effective": False, "answer_effective": False},
        full_content={"question": question, "history": history or []},
    )
    await tracked_progress({"event": "run_started", "run_id": run_id, "message": "分析任务已创建"})
    try:
        request = AgentRunRequest(question, history, run_id, thinking)
        result = await coordinate_agent_run(
            request,
            tracked_progress,
            implementation=_run_agent_impl,
        )
        result.setdefault("thinking_policy", {
            "requested": thinking,
            "context_effective": False,
            "answer_effective": False,
        })
        result["run_id"] = run_id
        result["status"] = "success"
        result["started_at"] = lifecycle.started_at
        result["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        result["duration_ms"] = lifecycle.duration_ms(time.perf_counter())
        result["first_token_ms"] = lifecycle.first_token_ms()
        context = result.get("context_resolution") if isinstance(result.get("context_resolution"), dict) else {}
        degraded = context.get("resolution_state") == "unavailable"
        reference_counts = _trace_reference_counts(result)
        tool_trace = result.get("tool_trace") if isinstance(result.get("tool_trace"), list) else []
        retrieval_duration_ms = round(sum(
            float(item.get("duration_ms", 0) or 0)
            for item in tool_trace
            if isinstance(item, dict) and item.get("tool") == "search_knowledge"
        ), 1)
        tool_duration_ms = round(sum(
            float(item.get("duration_ms", 0) or 0)
            for item in tool_trace
            if isinstance(item, dict) and item.get("tool") != "search_knowledge"
        ), 1)
        result["trace_semantics"] = {
            "schema_version": "1.0",
            **reference_counts,
            "retrieval_duration_ms": retrieval_duration_ms,
            "tool_duration_ms": tool_duration_ms,
        }
        emit(
            "agent_run_finished",
            run_id,
            status="success",
            outcome="degraded" if degraded else "completed",
            degraded=degraded,
            degradation_stage="contextualization" if degraded else None,
            degradation_reason=context.get("failure_reason") if degraded else None,
            fallback_action="continue_with_original_question" if degraded else None,
            session_id=session_id,
            user_message_id=user_message_id,
            mode=result.get("mode", "unknown"),
            duration_ms=result["duration_ms"],
            tool_count=len(tool_trace),
            tool_duration_ms=tool_duration_ms,
            retrieval_duration_ms=retrieval_duration_ms,
            **reference_counts,
            # Deprecated compatibility alias: this has always represented the
            # visible knowledge-source cards, not all evidence references.
            source_count=len(result.get("sources", [])),
            intent=result.get("intent_route", {}).get("intent", "unknown"),
            risk_level=result.get("intent_route", {}).get("risk_level", "unknown"),
            playbook_id=(result.get("domain_playbook", {}).get("selected_playbook") or {}).get("playbook_id"),
            playbook_version=(result.get("domain_playbook", {}).get("selected_playbook") or {}).get("playbook_version"),
            plan_id=result.get("execution_plan", {}).get("plan_id"),
            plan_status=result.get("execution_plan", {}).get("status"),
            guard_stop_reason=result.get("loop_guard", {}).get("stop_reason"),
            guard_total_calls=result.get("loop_guard", {}).get("total_calls", 0),
            guard_blocked_calls=result.get("loop_guard", {}).get("blocked_calls", 0),
            guard_unique_evidence_results=result.get("loop_guard", {}).get("unique_evidence_results", 0),
            evidence_required_coverage_pct=result.get("evidence_validation", {}).get("coverage", {}).get("required_coverage_pct", 0),
            evidence_risk_count=len(result.get("evidence_validation", {}).get("risks", [])),
            evidence_conflict_count=len(result.get("evidence_validation", {}).get("conflicts", [])),
            allowed_conclusion_strength=result.get("evidence_validation", {}).get("allowed_conclusion_strength"),
            answer_synthesis_status=result.get("answer_synthesis", {}).get("status"),
            answer_synthesis_moved_claims=result.get("answer_synthesis", {}).get("moved_claims", 0),
            answer_synthesis_invalid_sources=len(result.get("answer_synthesis", {}).get("invalid_source_refs", [])),
            full_content={
                "answer": result.get("answer"),
                "tool_trace": result.get("tool_trace", []),
                "sources": result.get("sources", []),
                "loop_guard": result.get("loop_guard", {}),
                "evidence_validation": result.get("evidence_validation", {}),
                "answer_contract": result.get("answer_contract", {}),
                "answer_synthesis": result.get("answer_synthesis", {}),
            },
        )
        return result
    except Exception as exc:
        await tracked_progress({"event": "run_failed", "run_id": run_id, "message": str(exc)})
        emit(
            "agent_run_finished",
            run_id,
            status="error",
            duration_ms=lifecycle.duration_ms(time.perf_counter()),
            error_type=type(exc).__name__,
            full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
        )
        raise
