from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable

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
from .agent_runtime.telemetry import (
    emit_answer_synthesis as _emit_answer_synthesis_runtime,
    notify as _notify_runtime,
    stream_answer as _stream_answer_runtime,
    trace_reference_counts as _trace_reference_counts_runtime,
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
    if intent_route.intent == "conversation":
        advertised_ids: tuple[str, ...] = ()
        validation = validate_evidence(execution_plan, playbook_selection.selected_playbook, [])
        contract = create_answer_contract(validation)
        if context_resolution and context_resolution.strategy == "context_clarification":
            candidates = context_resolution.candidate_messages
            lines = ["我没能可靠确定你指的是哪一条历史消息。请直接选择一条，或把对象重新写完整："]
            for item in candidates:
                content = " ".join(str(item.get("content") or "").strip().split())[:240]
                lines.append(f"\n- 消息 #{item.get('message_id')}：{content}")
            answer = "".join(lines)
        elif context_resolution and context_resolution.strategy == "semantic_recall":
            records = context_resolution.recalled_messages
            user_records = [item for item in records if item.get("role") == "user"]
            assistant_records = [item for item in records if item.get("role") == "assistant"]
            lines = ["根据当前会话中的原始记录："]
            for item in user_records:
                lines.append(
                    f"\n> 用户消息 #{item.get('message_id')}：{str(item.get('content') or '')[:700]}"
                )
            for item in assistant_records:
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                route = metadata.get("intent_route") if isinstance(metadata.get("intent_route"), dict) else {}
                process_steps = route.get("process_steps") if isinstance(route.get("process_steps"), list) else []
                scope = route.get("scope_resolution") if isinstance(route.get("scope_resolution"), dict) else {}
                scope_type = str(scope.get("scope_type") or "")
                tool_trace = metadata.get("tool_trace") if isinstance(metadata.get("tool_trace"), list) else []
                if scope_type == "unknown":
                    unresolved = scope.get("unresolved_mentions") if isinstance(scope.get("unresolved_mentions"), list) else []
                    scope_label = f"（{', '.join(str(value) for value in unresolved)}）" if unresolved else ""
                    lines.append(
                        f"\n该轮运行将制造范围记录为未知{scope_label}，没有把它映射为具体制程、设备或整厂范围；"
                        f"该轮实际执行了 {len(tool_trace)} 个工具。"
                    )
                elif (
                    route.get("intent") == "fab_diagnostic"
                    and not process_steps
                    and scope_type in {"", "fab"}
                ):
                    lines.append(
                        "\n该轮运行没有解析出具体制程或设备范围，实际按整厂综合诊断执行；"
                        "因此不能根据运行记录声称某个未解析缩写已被映射为特定制程。"
                    )
                elif scope.get("resolved_ids"):
                    lines.append(
                        f"\n该轮运行记录的分析范围是：{', '.join(str(value) for value in scope['resolved_ids'])}。"
                    )
                lines.append(
                    f"\n> 助手消息 #{item.get('message_id')} 摘要：{str(item.get('content') or '')[:700]}"
                )
            answer = "".join(lines)
        else:
            action = next((item for item in (turn_decision.actions if turn_decision else ()) if item.type in {"answer_meta", "recall_history", "route_task", "clarify"}), None)
            subject = action.subject if action and action.type == "answer_meta" else None
            detail = action.detail if action else "standard"
            answer, advertised_ids = build_meta_response(subject, detail, runtime_context=runtime_context)
            if context_resolution and context_resolution.strategy == "semantic_correction" and subject == "capabilities":
                answer = "明白，你要的是可验证的具体能力，而不是宽泛介绍。\n\n" + answer
            if run_id:
                emit("meta_response_built", run_id, template_version="conversation-v2", subject=subject, detail=detail, advertised_capability_count=len(advertised_ids))
        synthesis = synthesize_legacy_answer(
            answer,
            contract,
        )
        result = {
            "answer": synthesis.answer,
            "tool_trace": [],
            "sources": [],
            "mode": "deterministic",
            "intent_route": intent_route.to_dict(),
            "domain_playbook": playbook_selection.to_dict(),
            "execution_plan": execution_plan.to_dict(),
            "loop_guard": loop_guard.summary(),
            "evidence_validation": validation.to_dict(),
            "answer_contract": contract.to_dict(),
            "answer_synthesis": synthesis.report.to_dict(),
        }
        if turn_decision:
            result["turn_decision"] = turn_decision.to_dict()
            result["conversation_response"] = {
                "template_version": "conversation-v2",
                "advertised_capability_ids": list(advertised_ids),
                "advertised_capability_count": len(advertised_ids),
            }
        return result

    if execution_plan.status == "clarification_required":
        questions = (
            ("请把希望我回答或执行的内容再写完整一些。",)
            if intent_route.intent == "unknown"
            else execution_plan.clarification_questions
            or ("请补充要分析的制程、设备或时间范围。",)
        )
        validation = validate_evidence(execution_plan, playbook_selection.selected_playbook, [])
        contract = create_answer_contract(validation)
        synthesis = synthesize_legacy_answer(
            "为了生成可执行的分析路径，请先补充以下信息：\n\n" + "\n".join(
                f"{index}. {item}" for index, item in enumerate(questions, start=1)
            ),
            contract,
        )
        return {
            "answer": synthesis.answer,
            "tool_trace": [],
            "sources": [],
            "mode": "offline",
            "intent_route": intent_route.to_dict(),
            "domain_playbook": playbook_selection.to_dict(),
            "execution_plan": execution_plan.to_dict(),
            "loop_guard": loop_guard.summary(),
            "evidence_validation": validation.to_dict(),
            "answer_contract": contract.to_dict(),
            "answer_synthesis": synthesis.report.to_dict(),
        }

    if intent_route.intent == "general_knowledge":
        validation = validate_evidence(execution_plan, playbook_selection.selected_playbook, [])
        contract = create_answer_contract(validation)
        notice = "当前未配置可用的模型 API，无法生成通用知识回答。请检查服务端模型配置后重试。" if fallback_reason == "missing_api_key" else "模型暂时不可用，已启用本地规则；通用知识问题暂不能由本地规则可靠回答。"
        synthesis = synthesize_legacy_answer(
            notice,
            contract,
        )
        return {
            "answer": synthesis.answer,
            "tool_trace": [],
            "sources": [],
            "mode": "offline",
            "intent_route": intent_route.to_dict(),
            "domain_playbook": playbook_selection.to_dict(),
            "execution_plan": execution_plan.to_dict(),
            "loop_guard": loop_guard.summary(),
            "evidence_validation": validation.to_dict(),
            "answer_contract": contract.to_dict(),
            "answer_synthesis": synthesis.report.to_dict(),
        }

    local_trace: list[dict] = []
    observations: list[EvidenceObservation] = []

    def run_local_tool(name: str, handler: Callable[[], Any]) -> Any:
        decision = loop_guard.check_call(name, {})
        if not decision.allowed:
            local_trace.append({
                "tool": name,
                "status": "blocked",
                "error_code": decision.reason_code,
                "error": decision.message,
            })
            return None
        result = handler()
        loop_guard.record_result(name, result, True)
        observations.append(EvidenceObservation(name, {}, "success", result))
        local_trace.append({"tool": name, "status": "local"})
        return result

    loop_guard.begin_round()
    overview = run_local_tool("get_fab_overview", fab_overview)
    equipment = run_local_tool("get_equipment_health", equipment_health)
    loop_guard.finish_round()
    risky = (equipment or [])[:3]
    unavailable = fallback_reason != "missing_api_key"
    lines = ["模型暂时不可用，已启用本地规则分析。" if unavailable else "当前未配置可用的模型 API，因此返回本地规则分析。"]
    if overview is not None:
        lines.append(
            f"最近90天共完成 {overview['lots']} 个批次，综合良率 {overview['yield_pct']}%，"
            f"平均周期 {overview['avg_cycle_hours']} 小时。"
        )
    else:
        lines.append("运行时预算未允许查询工厂总览，因此当前没有可用于汇总的制造数据。")
    if risky:
        names = "、".join(f"{row['equipment_id']}（{row['health']}，{row['excursions']}次异常）" for row in risky)
        lines.append(f"优先关注设备：{names}。")
    lines.append("模型恢复后可获得针对问题的多轮工具分析。" if unavailable else "配置根目录 .env 的 FAB_MODEL_API_KEY 后，可获得针对问题的多轮工具分析。")
    validation = validate_evidence(execution_plan, playbook_selection.selected_playbook, observations)
    contract = create_answer_contract(validation)
    synthesis = synthesize_legacy_answer("\n\n".join(lines), contract)
    return {
        "answer": synthesis.answer,
        "tool_trace": local_trace,
        "sources": [],
        "mode": "offline",
        "intent_route": intent_route.to_dict(),
        "domain_playbook": playbook_selection.to_dict(),
        "execution_plan": execution_plan.to_dict(),
        "loop_guard": loop_guard.summary(),
        "evidence_validation": validation.to_dict(),
        "answer_contract": contract.to_dict(),
        "answer_synthesis": synthesis.report.to_dict(),
    }


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
    if intent_route.intent != "sop_lookup" or sources:
        return {"used": False, "reason": None, "disclosure": None}
    attempts = [item for item in observations if item.tool == "search_knowledge"]
    completed_attempts = [item for item in attempts if item.status in {"success", "error"}]
    if not completed_attempts:
        return {"used": False, "reason": None, "disclosure": None}
    successful_empty = any(
        item.status == "success" and item.result in (None, [])
        for item in completed_attempts
    )
    reason = "search_empty" if successful_empty else "search_unavailable"
    disclosure = (
        MODEL_KNOWLEDGE_DISCLOSURE
        if successful_empty
        else "知识库检索未获得可用内容。以下回答使用模型通用知识，仅供参考，不代表厂内 SOP、规格或当前生产事实。"
    )
    return {"used": True, "reason": reason, "disclosure": disclosure}


def _usable_knowledge_result(query: str, result: dict[str, Any]) -> bool:
    return usable_result(query, result)


def _normalize_general_knowledge_answer(answer: str) -> str:
    stripped = answer.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else stripped
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return answer
    if not isinstance(payload, dict):
        return answer
    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        return answer
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or function.get("name") != "submit_analysis":
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not isinstance(arguments, dict):
            continue
        content = arguments.get("content") or arguments.get("answer")
        if isinstance(content, str) and content.strip():
            return content.strip()
        conclusion = arguments.get("conclusion")
        if isinstance(conclusion, str) and conclusion.strip():
            return conclusion.strip()
    return answer


def _has_knowledge_fallback_disclosure(answer: str) -> bool:
    compact = re.sub(r"\s+", "", answer).lower()
    return bool(
        "个人知识库" in compact
        and "工厂知识库" in compact
        and any(term in compact for term in ("未检索到", "没有检索到", "无可用"))
        and any(term in compact for term in ("模型通用知识", "通用知识", "仅供参考"))
    )


def _ready_step_order(plan: ExecutionPlan) -> tuple[PlanStep, ...]:
    """Return a stable dependency order and fail closed on an invalid plan graph."""
    if plan.status != "ready":
        return ()
    by_id = {step.step_id: step for step in plan.steps}
    if len(by_id) != len(plan.steps):
        raise ValueError("ready 执行计划包含重复 step_id")
    missing = {
        dependency
        for step in plan.steps
        for dependency in step.depends_on
        if dependency not in by_id
    }
    if missing:
        raise ValueError(f"ready 执行计划引用未知依赖：{', '.join(sorted(missing))}")

    pending = list(plan.steps)
    completed: set[str] = set()
    ordered: list[PlanStep] = []
    while pending:
        ready = next(
            (step for step in pending if set(step.depends_on).issubset(completed)),
            None,
        )
        if ready is None:
            raise ValueError("ready 执行计划包含循环依赖")
        pending.remove(ready)
        ordered.append(ready)
        completed.add(ready.step_id)
    return tuple(ordered)


async def _execute_ready_plan(
    plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    run_id: str,
    progress: ProgressCallback | None,
) -> tuple[list[dict[str, Any]], list[EvidenceObservation], dict[str, dict[str, Any]]]:
    """Execute an approved ready plan without asking the model to select tools."""
    execution_started = time.perf_counter()
    ordered_steps = _ready_step_order(plan)
    trace: list[dict[str, Any]] = []
    observations: list[EvidenceObservation] = []
    sources: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, str] = {}
    emit(
        "ready_plan_execution_started",
        run_id,
        plan_id=plan.plan_id,
        step_count=len(ordered_steps),
        execution_mode="deterministic",
    )
    loop_guard.begin_round()

    for step in ordered_steps:
        arguments = dict(step.parameters)
        tool_started = time.perf_counter()
        failed_dependencies = tuple(
            dependency
            for dependency in step.depends_on
            if outcomes.get(dependency) != "success"
        )
        await _notify(progress, {
            "event": "tool_started",
            "tool": step.tool,
            "arguments": arguments,
            "plan_step_id": step.step_id,
            "execution_mode": "deterministic",
        })
        emit(
            "tool_call_started",
            run_id,
            tool=step.tool,
            tool_call_id=f"plan-{step.step_id}",
            plan_step_id=step.step_id,
            execution_mode="deterministic",
            full_content={"arguments": arguments},
        )

        if failed_dependencies:
            message = f"依赖步骤未成功：{', '.join(failed_dependencies)}"
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "blocked",
                "error_code": "dependency_failed",
                "error": message,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "blocked",
                error=message,
                source_ref=f"TOOL:{step.step_id}",
            ))
            outcomes[step.step_id] = "blocked"
            await _notify(progress, {"event": "tool_finished", **item})
            emit(
                "tool_call_blocked",
                run_id,
                tool=step.tool,
                tool_call_id=f"plan-{step.step_id}",
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                reason_code="dependency_failed",
                duration_ms=duration_ms,
                full_content={"arguments": arguments, "message": message},
            )
            emit(
                "tool_call_finished",
                run_id,
                status="blocked",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_code="dependency_failed",
            )
            continue

        decision = loop_guard.check_call(step.tool, arguments)
        if not decision.allowed:
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "blocked",
                "error_code": decision.reason_code,
                "error": decision.message,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "blocked",
                error=decision.message,
                source_ref=f"TOOL:{step.step_id}",
            ))
            outcomes[step.step_id] = "blocked"
            await _notify(progress, {"event": "tool_finished", **item})
            emit(
                "tool_call_blocked",
                run_id,
                tool=step.tool,
                tool_call_id=f"plan-{step.step_id}",
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                reason_code=decision.reason_code,
                signature_hash=decision.signature_hash,
                duration_ms=duration_ms,
                full_content={"arguments": arguments, "message": decision.message},
            )
            emit(
                "tool_call_finished",
                run_id,
                status="blocked",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_code=decision.reason_code,
            )
            continue

        try:
            handler = TOOL_HANDLERS.get(step.tool)
            if handler is None:
                raise ValueError(f"未知工具: {step.tool}")
            result = handler(**arguments)
            raw_rows = len(result) if isinstance(result, list) else (1 if result is not None else 0)
            if step.tool == "search_knowledge":
                result = [
                    item for item in result
                    if isinstance(item, dict)
                    and _usable_knowledge_result(str(arguments.get("query") or ""), item)
                ] if isinstance(result, list) else []
            if isinstance(result, list):
                result_limit = min(plan.budget.max_rows_per_call, step.estimated_result_limit)
                result = result[:max(0, result_limit)]
            if step.tool == "search_knowledge":
                for source in result:
                    reference_id = str(source.get("reference_id") or "")
                    if reference_id:
                        sources[reference_id] = source
            loop_guard.record_result(step.tool, result, True)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "success",
                result,
                source_ref=f"TOOL:{step.step_id}",
            ))
            row_count = len(result) if isinstance(result, list) else (1 if result is not None else 0)
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "ok",
                "rows": row_count,
                "raw_rows": raw_rows,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            outcomes[step.step_id] = "success"
            await _notify(progress, {"event": "tool_finished", **item})
            emit(
                "tool_call_finished",
                run_id,
                status="success",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                rows=row_count,
                raw_rows=raw_rows,
                full_content={"result": result},
            )
        except Exception as exc:
            loop_guard.record_result(step.tool, None, False)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "error",
                error=str(exc),
                source_ref=f"TOOL:{step.step_id}",
            ))
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "error",
                "error": str(exc),
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            outcomes[step.step_id] = "error"
            await _notify(progress, {"event": "tool_finished", **item})
            emit(
                "tool_call_finished",
                run_id,
                status="error",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
            )

    loop_guard.finish_round()
    if not loop_guard.force_synthesis:
        loop_guard.enter_synthesis(
            "deterministic_plan_completed",
            "确定性 ready 计划已完成，禁止继续选择业务工具。",
        )
    emit(
        "ready_plan_execution_finished",
        run_id,
        plan_id=plan.plan_id,
        execution_mode="deterministic",
        succeeded=sum(status == "success" for status in outcomes.values()),
        failed=sum(status == "error" for status in outcomes.values()),
        blocked=sum(status == "blocked" for status in outcomes.values()),
        duration_ms=round((time.perf_counter() - execution_started) * 1000, 1),
    )
    return trace, observations, sources


def _ready_synthesis_messages(
    question: str,
    plan: ExecutionPlan,
    validation: Any,
    contract: Any,
    observations: list[EvidenceObservation],
) -> list[dict[str, str]]:
    evidence = [
        {
            "source_ref": observation.source_ref,
            "tool": observation.tool,
            "status": observation.status,
            "result": observation.result if observation.status == "success" else None,
            "error": observation.error,
        }
        for observation in observations
    ]
    task = {
        "question": question,
        "plan_id": plan.plan_id,
        "intent": plan.route_intent,
        "playbook_id": plan.playbook_id,
        "playbook_version": plan.playbook_version,
        "scope": {
            "type": plan.scope_contract.primary_scope_type,
            "ids": plan.scope_contract.primary_scope_ids,
        },
        "validation": {
            "coverage": validation.coverage,
            "risks": [item.message for item in validation.risks],
            "conflicts": [item.message for item in validation.conflicts],
            "allowed_conclusion_strength": validation.allowed_conclusion_strength,
        },
        "evidence": evidence,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Fab Copilot 的最终综合器。业务工具已由服务端确定性执行；"
                "你只能依据下面的已验证证据调用 submit_analysis 一次，不能选择、请求或虚构业务工具。"
            ),
        },
        {"role": "system", "content": synthesizer_system_message(contract)},
        {
            "role": "user",
            "content": json.dumps(task, ensure_ascii=False, separators=(",", ":"), default=str),
        },
    ]


def _ready_synthesis_fallback(
    validation: Any,
    contract: Any,
    observations: list[EvidenceObservation],
    reason: str,
):
    succeeded = [item.source_ref for item in observations if item.status == "success"]
    failed = [item.source_ref for item in observations if item.status != "success"]
    coverage = validation.coverage
    lines = [
        "确定性取证已经完成，但模型综合阶段未能生成可验证的结构化结论。",
        (
            f"必需证据覆盖 {coverage['required_covered']}/{coverage['required_total']}；"
            f"允许的结论强度为 {validation.allowed_conclusion_strength}。"
        ),
        f"已完成来源：{', '.join(item for item in succeeded if item) or '无'}。",
    ]
    if failed:
        lines.append(f"未完成来源：{', '.join(item for item in failed if item)}。")
    lines.append(f"综合降级原因：{reason}。请稍后重试模型综合；本次不会重复执行制造数据工具。")
    return synthesize_legacy_answer("\n\n".join(lines), contract)


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
    """Make synthesis-only model calls; no business tool is exposed here."""
    request_payload: dict[str, Any] = {
        "model": connection.model,
        "messages": messages,
        "temperature": 0.15,
        "tools": [SUBMIT_ANALYSIS_TOOL],
        "max_tokens": 8192,
        **provider_request_options(connection.provider, thinking),
    }
    if not (connection.provider == "deepseek" and thinking):
        request_payload["tool_choice"] = "auto"

    for attempt in range(1, retry_budget + 2):
        started = time.perf_counter()
        emit(
            "model_call_started",
            run_id,
            phase="ready_plan_synthesis",
            iteration=1,
            attempt=attempt,
            model=connection.model,
            message_count=len(messages),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=request_payload.get("reasoning_effort"),
            business_tool_selection_enabled=False,
            full_content={"request": request_payload},
        )
        stream_state: dict[str, Any] = {
            "answer_emitted": False,
            "suppress_embedded_tool_json": True,
        }
        try:
            assistant, usage, response_id = await _stream_completion(
                client,
                endpoint,
                headers,
                request_payload,
                None,
                stream_state,
            )
        except Exception as exc:
            retryable = _retryable_model_error(exc)
            will_retry = retryable and attempt <= retry_budget
            emit(
                "model_call_finished",
                run_id,
                status="error",
                phase="ready_plan_synthesis",
                iteration=1,
                attempt=attempt,
                model=connection.model,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                error_type=type(exc).__name__,
                retryable=retryable,
                will_retry=will_retry,
                answer_emitted=False,
                business_tool_selection_enabled=False,
                failure_reason=_model_failure_reason(exc),
                full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
            )
            if not will_retry:
                raise
            delay_seconds = _model_retry_delay(settings.model_retry_base_seconds, attempt, exc)
            emit(
                "model_call_retry_scheduled",
                run_id,
                phase="ready_plan_synthesis",
                attempt=attempt,
                next_attempt=attempt + 1,
                delay_ms=round(delay_seconds * 1000, 1),
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(delay_seconds)
            continue
        emit(
            "model_call_finished",
            run_id,
            status="success",
            phase="ready_plan_synthesis",
            iteration=1,
            attempt=attempt,
            model=connection.model,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=stream_state.get("finish_reason") or (
                "tool_calls" if assistant.get("tool_calls") else "stop"
            ),
            response_id=response_id,
            first_content_ms=stream_state.get("first_content_ms"),
            max_content_gap_ms=stream_state.get("max_content_gap_ms", 0),
            content_delta_count=stream_state.get("content_delta_count", 0),
            content_chars=stream_state.get("content_chars", 0),
            stream_duration_ms=stream_state.get("stream_duration_ms"),
            reasoning_length=int(stream_state.get("reasoning_length", 0)),
            content_length=len(str(assistant.get("content") or "")),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=request_payload.get("reasoning_effort"),
            business_tool_selection_enabled=False,
            full_content={"response": _audit_assistant(assistant)},
        )
        return assistant, usage, response_id, stream_state
    raise RuntimeError("模型综合请求未返回结果")


async def _prefetch_general_knowledge(
    question: str,
    run_id: str,
    loop_guard: ToolLoopGuard,
    observations: list[EvidenceObservation],
    trace: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    progress: ProgressCallback | None,
) -> RetrievalDecision:
    retrieval_started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    scopes = required_scopes(question)
    rewrite = rewrite_query(question)
    queries = [("original", question)]
    if rewrite.changed:
        queries.append(("rewritten", rewrite.query))

    for query_variant, query in queries:
        loop_guard.begin_round()
        for scope in scopes:
            arguments = {"query": query, "limit": 10, "source_types": [scope]}
            tool_started = time.perf_counter()
            await _notify(progress, {
                "event": "tool_started",
                "tool": "search_knowledge",
                "arguments": arguments,
                "scope": scope,
                "query_variant": query_variant,
            })
            emit(
                "tool_call_started",
                run_id,
                tool="search_knowledge",
                tool_call_id=f"prefetch-{query_variant}-{scope}",
                retrieval_scope=scope,
                query_variant=query_variant,
                full_content={"arguments": arguments},
            )
            guard_decision = loop_guard.check_call("search_knowledge", arguments)
            if not guard_decision.allowed:
                duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                attempt = {
                    "scope": scope,
                    "query_variant": query_variant,
                    "query": query,
                    "status": "blocked",
                    "raw_count": 0,
                    "usable_count": 0,
                    "error_code": guard_decision.reason_code,
                }
                attempts.append(attempt)
                observations.append(EvidenceObservation(
                    "search_knowledge", arguments, "blocked", error=guard_decision.message
                ))
                item = {
                    "tool": "search_knowledge",
                    "arguments": arguments,
                    "status": "blocked",
                    "rows": 0,
                    "error_code": guard_decision.reason_code,
                    "error": guard_decision.message,
                    "duration_ms": duration_ms,
                    "retrieval_scope": scope,
                    "query_variant": query_variant,
                }
                trace.append(item)
                await _notify(progress, {"event": "tool_finished", **item})
                continue

            try:
                result = TOOL_HANDLERS["search_knowledge"](**arguments)
                raw_count = len(result) if isinstance(result, list) else 0
                usable = [
                    item for item in result
                    if isinstance(item, dict) and _usable_knowledge_result(query, item)
                ] if isinstance(result, list) else []
                for source in usable:
                    sources[str(source["reference_id"])] = source
                loop_guard.record_result("search_knowledge", usable, True)
                observations.append(EvidenceObservation("search_knowledge", arguments, "success", usable))
                duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                attempts.append({
                    "scope": scope,
                    "query_variant": query_variant,
                    "query": query,
                    "status": "success",
                    "raw_count": raw_count,
                    "usable_count": len(usable),
                    "reference_ids": [str(item.get("reference_id")) for item in usable],
                })
                trace_item = {
                    "tool": "search_knowledge",
                    "arguments": arguments,
                    "status": "ok",
                    "rows": len(usable),
                    "raw_rows": raw_count,
                    "duration_ms": duration_ms,
                    "retrieval_scope": scope,
                    "query_variant": query_variant,
                }
                trace.append(trace_item)
                await _notify(progress, {"event": "tool_finished", **trace_item})
                emit(
                    "tool_call_finished",
                    run_id,
                    status="success",
                    tool="search_knowledge",
                    duration_ms=duration_ms,
                    retrieval_scope=scope,
                    query_variant=query_variant,
                    raw_rows=raw_count,
                    rows=len(usable),
                    full_content={"result": usable},
                )
            except Exception as exc:
                loop_guard.record_result("search_knowledge", None, False)
                observations.append(EvidenceObservation("search_knowledge", arguments, "error", error=str(exc)))
                duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                attempts.append({
                    "scope": scope,
                    "query_variant": query_variant,
                    "query": query,
                    "status": "error",
                    "raw_count": 0,
                    "usable_count": 0,
                    "error_type": type(exc).__name__,
                })
                trace_item = {
                    "tool": "search_knowledge",
                    "arguments": arguments,
                    "status": "error",
                    "rows": 0,
                    "error": str(exc),
                    "duration_ms": duration_ms,
                    "retrieval_scope": scope,
                    "query_variant": query_variant,
                }
                trace.append(trace_item)
                await _notify(progress, {"event": "tool_finished", **trace_item})
                emit(
                    "tool_call_finished",
                    run_id,
                    status="error",
                    tool="search_knowledge",
                    duration_ms=duration_ms,
                    retrieval_scope=scope,
                    query_variant=query_variant,
                    error_type=type(exc).__name__,
                    full_content={"error_message": str(exc)},
                )
        loop_guard.finish_round()

    decision = assess_retrieval(attempts, list(sources.values()), rewrite)
    decision_payload = decision.to_dict()
    emit(
        "knowledge_retrieval_decided",
        run_id,
        state=decision.state,
        reason=decision.reason,
        attempted_scopes=list(decision.attempted_scopes),
        source_counts=decision.source_counts,
        rewritten=bool(decision.rewritten_query),
        model_knowledge_allowed=decision.model_knowledge_allowed,
        duration_ms=round((time.perf_counter() - retrieval_started) * 1000, 1),
        full_content={"retrieval_decision": decision_payload},
    )
    await _notify(progress, {
        "event": "stage",
        "stage": "knowledge_retrieval",
        "message": (
            f"知识检索完成 · 个人 {decision.source_counts['personal']} · "
            f"工厂 {decision.source_counts['knowledge']} · 案例 {decision.source_counts['case']}"
        ),
        "retrieval_decision": decision_payload,
    })
    return decision


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
            return {
                "answer": synthesis.answer,
                "tool_trace": trace,
                "sources": [],
                "mode": "deterministic-fallback",
                "model": "local-rules",
                "usage": context_usage,
                "intent_route": route_payload,
                "domain_playbook": playbook_payload,
                "execution_plan": plan_payload,
                "loop_guard": loop_guard.summary(),
                "evidence_validation": evidence_validation.to_dict(),
                "answer_contract": answer_contract.to_dict(),
                "answer_synthesis": synthesis.report.to_dict(),
                "context_resolution": context_resolution.to_dict(),
                "knowledge_fallback": {"used": False, "reason": None, "disclosure": None},
                "retrieval_decision": {
                    "state": "NOT_APPLICABLE", "reason": None, "attempted_scopes": [],
                    "attempts": [], "selected_reference_ids": [],
                    "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
                    "rewritten_query": None, "assumptions": [],
                    "model_knowledge_allowed": False, "disclosure": None,
                },
                "thinking_policy": {
                    "requested": thinking,
                    "context_effective": False,
                    "answer_effective": False,
                },
                "turn_decision": turn_decision.to_dict(),
                "model_health": {
                    "requested_model_id": selected_model_id,
                    "fallback_reason": fallback_reason,
                    **model_health,
                },
                "execution_mode": "deterministic_ready_plan",
                "model_tool_selection_calls": 0,
            }
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
        cited_knowledge_refs = {
            reference for reference in synthesis_report.source_refs
            if not reference.startswith("TOOL:")
        }
        if intent_route.intent == "general_knowledge":
            cited_knowledge_refs.update(retrieval_decision_payload["selected_reference_ids"])
        return {
            "answer": answer,
            "tool_trace": trace,
            "sources": [
                source for reference, source in sources.items()
                if reference in cited_knowledge_refs
            ],
            "mode": "deepseek",
            "model": connection.model,
            "usage": total_usage,
            "intent_route": route_payload,
            "domain_playbook": playbook_payload,
            "execution_plan": plan_payload,
            "loop_guard": loop_guard.summary(),
            "evidence_validation": evidence_validation.to_dict(),
            "answer_contract": answer_contract.to_dict(),
            "answer_synthesis": synthesis_report.to_dict(),
            "context_resolution": context_resolution.to_dict(),
            "knowledge_fallback": knowledge_fallback,
            "retrieval_decision": retrieval_decision_payload,
            "thinking_policy": {
                "requested": thinking,
                "context_effective": False,
                "answer_effective": thinking_answer_effective,
            },
            "turn_decision": turn_decision.to_dict(),
        }

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

            tool_calls = assistant.get("tool_calls") or []
            if len(tool_calls) == 1 and tool_calls[0].get("function", {}).get("name") == "submit_analysis":
                raw_arguments = tool_calls[0].get("function", {}).get("arguments") or "{}"
                try:
                    submission = json.loads(raw_arguments)
                    if not isinstance(submission, dict):
                        raise ValueError("submit_analysis 参数必须是 JSON 对象")
                    synthesis = synthesize_submission(
                        submission,
                        answer_contract,
                        list(sources.values()),
                        status="structured",
                    )
                except Exception as exc:
                    emit(
                        "answer_submission_rejected",
                        run_id,
                        iteration=1,
                        error_type="invalid_json",
                        error_message=str(exc),
                        execution_mode="synthesis_only",
                    )
                    synthesis = _ready_synthesis_fallback(
                        evidence_validation,
                        answer_contract,
                        evidence_observations,
                        "模型提交的结构化结果无效",
                    )
            elif not tool_calls and str(assistant.get("content") or "").strip():
                synthesis = synthesize_legacy_answer(
                    str(assistant.get("content") or ""),
                    answer_contract,
                    list(sources.values()),
                )
            else:
                synthesis = _ready_synthesis_fallback(
                    evidence_validation,
                    answer_contract,
                    evidence_observations,
                    "模型没有提交允许的 submit_analysis 结果",
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

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        for iteration in range(loop_guard.max_model_iterations):
            if iteration == loop_guard.max_model_iterations - 1 and loop_guard.total_calls > 0:
                loop_guard.reserve_final_iteration()
            synthesis_only = loop_guard.force_synthesis
            if synthesis_only and applied_synthesis_reason != loop_guard.stop_reason:
                messages.append({"role": "system", "content": loop_guard.synthesis_instruction()})
                applied_synthesis_reason = loop_guard.stop_reason
            await _notify(progress, {
                "event": "stage",
                "stage": "synthesis" if synthesis_only else "planning",
                "iteration": iteration + 1,
                "message": (
                    f"工具执行已停止，正在基于现有证据组织结论 · {loop_guard.stop_message}"
                    if synthesis_only
                    else "正在理解问题并规划分析路径"
                    if iteration == 0
                    else "正在结合工具结果判断是否继续，并组织结论"
                ),
            })
            request_payload = {
                "model": connection.model,
                "messages": messages,
                "temperature": 0.15,
                **provider_request_options(connection.provider, thinking),
            }
            if intent_route.intent not in {"general_knowledge", "conversation"}:
                request_payload["tools"] = (
                    [SUBMIT_ANALYSIS_TOOL]
                    if synthesis_only and answer_contract.status == "required"
                    else TOOLS
                )
                if not (connection.provider == "deepseek" and thinking):
                    request_payload["tool_choice"] = (
                        "none" if synthesis_only and answer_contract.status != "required" else "auto"
                    )
                if synthesis_only and answer_contract.status == "required":
                    request_payload["max_tokens"] = 8192
            retry_budget = 0 if main_recovery_trial else settings.model_max_retries
            for attempt in range(1, retry_budget + 2):
                model_started = time.perf_counter()
                emit(
                    "model_call_started",
                    run_id,
                    phase="agent_loop",
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=connection.model,
                    message_count=len(messages),
                    thinking_requested=thinking,
                    thinking_effective=thinking,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    full_content={"request": request_payload},
                )
                stream_state = {
                    "answer_emitted": False,
                    "suppress_embedded_tool_json": intent_route.intent == "general_knowledge",
                    "required_disclosure": knowledge_fallback.get("disclosure") or "",
                }
                try:
                    assistant, usage, response_id = await _stream_completion(
                        client,
                        endpoint,
                        {"Authorization": f"Bearer {connection.api_key}", "Content-Type": "application/json"},
                        request_payload,
                        None if answer_contract.status == "required" else progress,
                        stream_state,
                    )
                except Exception as exc:
                    availability_failure = _retryable_model_error(exc)
                    retryable = availability_failure and not stream_state["answer_emitted"]
                    will_retry = retryable and attempt <= retry_budget
                    emit(
                        "model_call_finished",
                        run_id,
                        status="error",
                        iteration=iteration + 1,
                        attempt=attempt,
                        model=connection.model,
                        duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                        error_type=type(exc).__name__,
                        phase="agent_loop",
                        retryable=retryable,
                        will_retry=will_retry,
                        answer_emitted=stream_state["answer_emitted"],
                        content_length=int(stream_state.get("content_chars", 0)),
                        thinking_requested=thinking,
                        thinking_effective=thinking,
                        reasoning_effort=request_payload.get("reasoning_effort"),
                        failure_reason=_model_failure_reason(exc),
                        full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                    )
                    if not will_retry:
                        if availability_failure and health_enabled:
                            health, transition = record_model_failure(
                                selected_model_id, _model_error_category(exc),
                                threshold=settings.model_circuit_failure_threshold,
                                cooldown_seconds=settings.model_circuit_cooldown_seconds,
                            )
                            emit("model_health_failure_recorded", run_id, model_id=selected_model_id, health=health, transition=transition)
                        if availability_failure and not stream_state["answer_emitted"]:
                            emit("model_local_fallback_activated", run_id, model_id=selected_model_id, reason="upstream_unavailable", health=health)
                            result = _offline_answer(
                                analysis_question, intent_route, playbook_selection, execution_plan, loop_guard,
                                context_resolution, fallback_reason="upstream_unavailable",
                            )
                            result.update({
                                "model": "local-rules", "usage": total_usage,
                                "context_resolution": context_resolution.to_dict(),
                                "model_health": {"requested_model_id": selected_model_id, "fallback_reason": "upstream_unavailable", **health},
                            })
                            for item in result["tool_trace"]:
                                await _notify(progress, {"event": "tool_started", "tool": item["tool"], "arguments": {}})
                                await _notify(progress, {"event": "tool_finished", **item})
                            await _stream_answer(progress, result["answer"])
                            return result
                        raise
                    delay_seconds = _model_retry_delay(settings.model_retry_base_seconds, attempt, exc)
                    emit(
                        "model_call_retry_scheduled",
                        run_id,
                        iteration=iteration + 1,
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        delay_ms=round(delay_seconds * 1000, 1),
                        error_type=type(exc).__name__,
                    )
                    await _notify(progress, {
                        "event": "stage",
                        "stage": "retrying",
                        "iteration": iteration + 1,
                        "attempt": attempt + 1,
                        "message": f"模型服务暂时不可用，正在进行第 {attempt + 1} 次请求",
                    })
                    await asyncio.sleep(delay_seconds)
                    continue
                emit(
                    "model_call_finished",
                    run_id,
                    status="success",
                    phase="agent_loop",
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=connection.model,
                    duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    finish_reason=stream_state.get("finish_reason") or (
                        "tool_calls" if assistant.get("tool_calls") else "stop"
                    ),
                    response_id=response_id,
                    first_content_ms=stream_state.get("first_content_ms"),
                    max_content_gap_ms=stream_state.get("max_content_gap_ms", 0),
                    content_delta_count=stream_state.get("content_delta_count", 0),
                    content_chars=stream_state.get("content_chars", 0),
                    stream_duration_ms=stream_state.get("stream_duration_ms"),
                    reasoning_length=int(stream_state.get("reasoning_length", 0)),
                    content_length=len(str(assistant.get("content") or "")),
                    thinking_requested=thinking,
                    thinking_effective=thinking,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    full_content={"response": _audit_assistant(assistant)},
                )
                thinking_answer_effective = thinking_answer_effective or thinking
                if health_enabled:
                    health, transition = record_model_success(selected_model_id)
                    if transition:
                        emit("model_circuit_recovered", run_id, model_id=selected_model_id, health=health)
                break
            for key in total_usage:
                total_usage[key] += int(usage.get(key, 0) or 0)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                raw_answer = assistant.get("content") or (
                    loop_guard.termination_answer()
                    if loop_guard.force_synthesis
                    else "分析完成，但模型没有返回文字。"
                )
                if intent_route.intent == "general_knowledge":
                    raw_answer = _normalize_general_knowledge_answer(raw_answer)
                disclosure = knowledge_fallback.get("disclosure")
                if (
                    knowledge_fallback["used"]
                    and disclosure
                    and not _has_knowledge_fallback_disclosure(raw_answer)
                ):
                    raw_answer = f"> {disclosure}\n\n{raw_answer}"
                synthesis = synthesize_legacy_answer(raw_answer, answer_contract, list(sources.values()))
                _emit_answer_synthesis(run_id, synthesis.report)
                if (
                    answer_contract.status == "required"
                    or (
                        intent_route.intent == "general_knowledge"
                        and not stream_state.get("answer_emitted")
                    )
                    or not assistant.get("content")
                ):
                    await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "正在按证据等级整理结构化答案"})
                    await _stream_answer(progress, synthesis.answer)
                return build_result(synthesis.answer, synthesis.report)

            if len(tool_calls) == 1 and tool_calls[0].get("function", {}).get("name") == "submit_analysis":
                raw_arguments = tool_calls[0].get("function", {}).get("arguments") or "{}"
                submission_error: str | None = None
                try:
                    submission = json.loads(raw_arguments)
                    if not isinstance(submission, dict):
                        raise ValueError("结构化答案必须是 JSON 对象")
                except Exception as exc:
                    submission = {}
                    submission_error = str(exc)
                if submission_error and iteration < loop_guard.max_model_iterations - 1:
                    emit(
                        "answer_submission_rejected",
                        run_id,
                        iteration=iteration + 1,
                        error_type="invalid_json",
                        error_message=submission_error,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_calls[0].get("id") or "submit-analysis-invalid",
                        "content": json.dumps({
                            "ok": False,
                            "error": "submit_analysis 参数不是完整 JSON，请缩短内容并重新提交。",
                        }, ensure_ascii=False),
                    })
                    await _notify(progress, {
                        "event": "stage",
                        "stage": "synthesis",
                        "message": "结构化答案不完整，正在精简并重新提交",
                    })
                    continue
                synthesis = synthesize_submission(
                    submission,
                    answer_contract,
                    list(sources.values()),
                    status="structured" if submission else "repaired",
                )
                await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "结构化答案已通过证据约束，正在输出"})
                _emit_answer_synthesis(run_id, synthesis.report)
                await _stream_answer(progress, synthesis.answer)
                return build_result(synthesis.answer, synthesis.report)

            loop_guard.begin_round()
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                tool_started = time.perf_counter()
                raw_arguments = function.get("arguments") or "{}"
                parse_error: Exception | None = None
                try:
                    arguments = json.loads(raw_arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("工具参数必须是 JSON 对象")
                except Exception as exc:
                    parse_error = exc
                    arguments = {"_raw": str(raw_arguments)[:1000]}

                if name == "submit_analysis":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or "submit-analysis-rejected",
                        "content": json.dumps({
                            "ok": False,
                            "error": "submit_analysis 必须单独调用，不能与数据工具处于同一轮。",
                        }, ensure_ascii=False),
                    })
                    continue

                await _notify(progress, {"event": "tool_started", "tool": name, "arguments": arguments})
                emit(
                    "tool_call_started",
                    run_id,
                    tool=name or "unknown",
                    tool_call_id=call.get("id"),
                    full_content={"arguments": arguments},
                )
                decision = loop_guard.check_call(name or "unknown", arguments)
                if not decision.allowed:
                    tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    blocked_item = {
                        "tool": name or "unknown",
                        "arguments": arguments,
                        "status": "blocked",
                        "error_code": decision.reason_code,
                        "error": decision.message,
                        "duration_ms": tool_duration_ms,
                    }
                    trace.append(blocked_item)
                    evidence_observations.append(EvidenceObservation(
                        name or "unknown",
                        arguments,
                        "blocked",
                        error=decision.message,
                    ))
                    await _notify(progress, {"event": "tool_finished", **blocked_item})
                    emit(
                        "tool_call_blocked",
                        run_id,
                        tool=name or "unknown",
                        tool_call_id=call.get("id"),
                        reason_code=decision.reason_code,
                        signature_hash=decision.signature_hash,
                        duration_ms=tool_duration_ms,
                        full_content={"arguments": arguments, "message": decision.message},
                    )
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="blocked",
                        tool=name or "unknown",
                        duration_ms=tool_duration_ms,
                        error_code=decision.reason_code,
                    )
                    content = json.dumps(
                        {"ok": False, "error_code": decision.reason_code, "error": decision.message},
                        ensure_ascii=False,
                    )
                    messages.append({"role": "tool", "tool_call_id": call.get("id") or decision.signature_hash, "content": content})
                    continue

                try:
                    if parse_error is not None:
                        raise ValueError(f"工具参数不是有效 JSON 对象: {parse_error}")
                    handler = TOOL_HANDLERS.get(name)
                    if handler is None:
                        raise ValueError(f"未知工具: {name}")
                    result = handler(**arguments)
                    if name == "search_knowledge":
                        raw_count = len(result) if isinstance(result, list) else 0
                        result = [
                            item for item in result
                            if isinstance(item, dict)
                            and _usable_knowledge_result(str(arguments.get("query") or ""), item)
                        ] if isinstance(result, list) else []
                        if len(result) != raw_count:
                            emit(
                                "knowledge_results_filtered",
                                run_id,
                                raw_count=raw_count,
                                usable_count=len(result),
                                filtered_count=raw_count - len(result),
                            )
                        for source in result:
                            sources[source["reference_id"]] = source
                    loop_guard.record_result(name, result, True)
                    planned_step = next((
                        step for step in execution_plan.steps
                        if step.tool == name and step.parameters == arguments
                    ), None)
                    evidence_observations.append(EvidenceObservation(
                        name, arguments, "success", result,
                        source_ref=f"TOOL:{planned_step.step_id}" if planned_step else f"TOOL:{call.get('id') or name}",
                    ))
                    row_count = len(result) if isinstance(result, list) else 1
                    tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    trace.append({"tool": name, "arguments": arguments, "status": "ok", "rows": row_count, "duration_ms": tool_duration_ms})
                    await _notify(progress, {
                        "event": "tool_finished",
                        "tool": name,
                        "arguments": arguments,
                        "status": "ok",
                        "rows": row_count,
                        "duration_ms": tool_duration_ms,
                    })
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="success",
                        tool=name,
                        duration_ms=tool_duration_ms,
                        rows=row_count,
                        full_content={"result": result},
                    )
                    content = json.dumps({"ok": True, "data": result}, ensure_ascii=False, default=str)
                except Exception as exc:
                    loop_guard.record_result(name or "unknown", None, False)
                    evidence_observations.append(EvidenceObservation(
                        name or "unknown", arguments, "error", error=str(exc),
                        source_ref=f"TOOL:{call.get('id') or name or 'unknown'}",
                    ))
                    trace.append({"tool": name or "unknown", "arguments": arguments, "status": "error", "error": str(exc)})
                    await _notify(progress, {
                        "event": "tool_finished",
                        "tool": name or "unknown",
                        "arguments": arguments,
                        "status": "error",
                        "error": str(exc),
                    })
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="error",
                        tool=name or "unknown",
                        duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
                        error_type=type(exc).__name__,
                        full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                    )
                    content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call.get("id") or decision.signature_hash, "content": content})

            loop_guard.finish_round()
            evidence_validation = validate_evidence(execution_plan, selected_playbook, evidence_observations)
            coverage = evidence_validation.coverage
            if (
                execution_plan.status == "ready"
                and coverage["required_total"] > 0
                and coverage["required_covered"] == coverage["required_total"]
            ):
                loop_guard.enter_synthesis(
                    "required_evidence_complete",
                    f"执行计划的 {coverage['required_total']} 组必需证据已全部覆盖。",
                )
            if intent_route.intent != "general_knowledge":
                knowledge_fallback = _knowledge_fallback_state(intent_route, evidence_observations, sources)
            answer_contract = create_answer_contract(
                evidence_validation,
                list(sources.values()),
                allow_model_knowledge_fallback=knowledge_fallback["used"],
            )
            messages.append({"role": "system", "content": validator_system_message(evidence_validation)})
            messages.append({"role": "system", "content": synthesizer_system_message(answer_contract)})
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
            })
            _emit_evidence_validation(run_id, iteration + 1, evidence_validation.to_dict())
            if knowledge_fallback["used"] and not fallback_announced:
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
            guard_summary = loop_guard.summary()
            emit(
                "loop_guard_round_finished",
                run_id,
                iteration=iteration + 1,
                total_calls=guard_summary["total_calls"],
                unique_evidence_results=guard_summary["unique_evidence_results"],
                blocked_calls=guard_summary["blocked_calls"],
                consecutive_no_progress_rounds=guard_summary["consecutive_no_progress_rounds"],
                force_synthesis=guard_summary["force_synthesis"],
                stop_reason=guard_summary["stop_reason"],
            )

    loop_guard.enter_synthesis(
        "model_iteration_limit",
        f"模型已达到 {loop_guard.max_model_iterations} 轮执行上限。",
    )
    answer = loop_guard.termination_answer()
    synthesis = synthesize_legacy_answer(answer, answer_contract, list(sources.values()))
    _emit_answer_synthesis(run_id, synthesis.report)
    await _stream_answer(progress, synthesis.answer)
    return build_result(synthesis.answer, synthesis.report)


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
