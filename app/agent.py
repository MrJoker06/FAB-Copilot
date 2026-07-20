from __future__ import annotations

import asyncio
import inspect
import json
import random
import re
import time
import traceback
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable

import httpx

from .answer_synthesizer import (
    MODEL_KNOWLEDGE_DISCLOSURE,
    SUBMIT_ANALYSIS_TOOL,
    AnswerSynthesisReport,
    create_answer_contract,
    synthesize_legacy_answer,
    synthesize_submission,
    synthesizer_system_message,
)
from .audit import CONTENT_MODE, content_fingerprint, emit
from .config import get_settings
from .context_resolver import (
    CONTEXTUALIZER_RESPONSE_FORMAT,
    ContextResolution,
    build_contextualizer_messages,
    context_clarification_resolution,
    context_system_message,
    resolve_question_context,
    semantic_context_resolution,
    unresolved_context,
)
from .domain_playbooks import PlaybookSelection, playbook_system_message, select_playbook
from .evidence_validator import EvidenceObservation, validate_evidence, validator_system_message
from .enterprise_data import enterprise_data_manifest, enterprise_fab_summary, query_enterprise_data
from .intent_router import (
    IntentRoute,
    apply_semantic_intent_hint,
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
from .model_registry import effective_agent_settings
from .planner import ExecutionPlan, create_execution_plan, planner_system_message
from .processes import ANALYSIS_SCOPES, MANUFACTURING_STEPS
from .rag import search_agent_knowledge
from .reports import (
    defect_pareto,
    equipment_health,
    equipment_productivity,
    fab_overview,
    process_capability,
    recent_excursions,
    safe_select,
    sensor_summary,
    yield_trend,
)


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


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


DATE_PROPERTIES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}

TOOLS = [
    {"type": "function", "function": {"name": "get_enterprise_data_manifest", "description": "查询当前租户可用的企业数据实体、虚拟数据规模、分页方式和模拟数据标记", "parameters": _schema({})}},
    {"type": "function", "function": {"name": "get_enterprise_fab_summary", "description": "对当前租户的亿级企业模拟数据执行服务端聚合，返回范围内规模、KPI、设备风险和血缘。结果是确定性投影，不是真实生产观测", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}})}},
    {"type": "function", "function": {"name": "query_enterprise_data", "description": "从当前租户的企业模拟数据接口抽取最多50条记录用于接口和数据形态分析；结果是样本，不能代表全量统计", "parameters": _schema({"entity": {"type": "string", "enum": ["lots", "process-runs", "sensor-events"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, **DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}, "product": {"type": "string"}, "status": {"type": "string", "enum": ["Completed", "Running", "Hold"]}, "signal_name": {"type": "string"}}, ["entity"])}},
    {"type": "function", "function": {"name": "get_fab_overview", "description": "查询工厂批次、晶圆、良率、周期、hold和异常总览", "parameters": _schema(DATE_PROPERTIES)}},
    {"type": "function", "function": {"name": "get_yield_trend", "description": "按周查询良率和周期趋势，可按产品过滤", "parameters": _schema({**DATE_PROPERTIES, "product": {"type": "string", "description": "产品名，如 Nova-P1"}})}},
    {"type": "function", "function": {"name": "get_equipment_health", "description": "查询设备运行数、异常数、缺陷密度、停机和健康状态，可按站点或设备过滤", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}})}},
    {"type": "function", "function": {"name": "get_equipment_productivity", "description": "按SEMI E10状态查询设备生产、待机、工程和停机时间占比，可按站点或设备过滤", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}})}},
    {"type": "function", "function": {"name": "get_process_capability", "description": "按站点关键量测和规格限查询各设备Cpk", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}})}},
    {"type": "function", "function": {"name": "get_defect_pareto", "description": "查询缺陷类型Pareto和受影响批次数，可按站点过滤", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}})}},
    {"type": "function", "function": {"name": "get_recent_excursions", "description": "查询最近的制程异常批次及量测值，可按站点或设备过滤", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}})}},
    {"type": "function", "function": {"name": "get_sensor_summary", "description": "按站点、设备或信号查询传感器均值、范围、缺失和异常标记", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}, "signal_name": {"type": "string"}})}},
    {"type": "function", "function": {"name": "search_knowledge", "description": "联合检索当前用户个人知识、厂内SOP、控制计划、分析方法与已验证历史案例。支持中英文制程术语召回，可按元数据过滤，返回可解释评分和reference_id", "parameters": _schema({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}, "process_step": {"type": "string", "enum": list(ANALYSIS_SCOPES)}, "equipment_id": {"type": "string"}, "defect_type": {"type": "string"}, "source_types": {"type": "array", "items": {"type": "string", "enum": ["personal", "knowledge", "case"]}}}, ["query"])}},
    {"type": "function", "function": {"name": "query_manufacturing_data", "description": "在固定报表不足时执行只读SQLite SELECT。只能访问白名单表，最多返回100行", "parameters": _schema({"sql": {"type": "string", "description": "单条SELECT语句，SQLite语法"}}, ["sql"])}},
    SUBMIT_ANALYSIS_TOOL,
]


TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "get_enterprise_data_manifest": enterprise_data_manifest,
    "get_enterprise_fab_summary": enterprise_fab_summary,
    "query_enterprise_data": query_enterprise_data,
    "get_fab_overview": fab_overview,
    "get_yield_trend": yield_trend,
    "get_equipment_health": equipment_health,
    "get_equipment_productivity": equipment_productivity,
    "get_process_capability": process_capability,
    "get_defect_pareto": defect_pareto,
    "get_recent_excursions": recent_excursions,
    "get_sensor_summary": sensor_summary,
    "search_knowledge": search_agent_knowledge,
    "query_manufacturing_data": safe_select,
}

ProgressCallback = Callable[[dict], Any]


async def _notify(progress: ProgressCallback | None, event: dict) -> None:
    if progress is None:
        return
    result = progress(event)
    if inspect.isawaitable(result):
        await result


async def _stream_answer(progress: ProgressCallback | None, answer: str) -> None:
    for start in range(0, len(answer), 120):
        await _notify(progress, {"event": "answer_delta", "delta": answer[start:start + 120]})
        await asyncio.sleep(0)


def _emit_answer_synthesis(run_id: str, report: AnswerSynthesisReport) -> None:
    payload = report.to_dict()
    emit(
        "answer_synthesis_completed",
        run_id,
        plan_id=report.plan_id,
        status=report.status,
        allowed_conclusion_strength=report.allowed_conclusion_strength,
        source_count=len(report.source_refs),
        invalid_source_count=len(report.invalid_source_refs),
        moved_claims=report.moved_claims,
        wording_adjustment_count=len(report.wording_adjustments),
        **({"answer_synthesis": payload} if CONTENT_MODE == "full" else {}),
    )


def _offline_answer(
    question: str,
    intent_route: IntentRoute,
    playbook_selection: PlaybookSelection,
    execution_plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    context_resolution: ContextResolution | None = None,
) -> dict:
    if intent_route.intent == "conversation":
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
            answer = (
                "我是 Fab Copilot，面向半导体制造场景的分析助手。"
                "我可以查询制造报表与模拟数据、检索当前用户的个人知识和工厂知识、引用历史案例，"
                "并把事实、推断、建议和证据限制分开说明。对于一般技术问题，我会先检索可用知识，"
                "证据不足时才明确标注并使用模型通用知识补充。"
            )
        synthesis = synthesize_legacy_answer(
            answer,
            contract,
        )
        return {
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

    if execution_plan.status == "clarification_required":
        questions = (
            (
                "分析制程能力或 Cpk，请同时指定制程站点。",
                "分析良率、缺陷或趋势，请说明关注的产品或时间范围。",
                "分析设备故障、报警或停机，请提供设备编号。",
                "追踪批次、晶圆或 Hold，请提供完整批次编号。",
                "查询 SOP、正式知识、历史案例或基础工艺解释。",
            )
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
        synthesis = synthesize_legacy_answer(
            "当前未配置可用的模型 API，无法生成通用知识回答。请检查服务端模型配置后重试。",
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
    lines = ["当前未配置可用的 DeepSeek API，因此返回本地规则分析。"]
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
    lines.append("配置根目录 .env 的 DEEPSEEK_API_KEY 后，可获得针对问题的多轮工具分析。")
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


async def _prefetch_general_knowledge(
    question: str,
    run_id: str,
    loop_guard: ToolLoopGuard,
    observations: list[EvidenceObservation],
    trace: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    progress: ProgressCallback | None,
) -> RetrievalDecision:
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
                **({"arguments": arguments} if CONTENT_MODE == "full" else {}),
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
                    **({"result": usable} if CONTENT_MODE == "full" else {}),
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
                    **({"error_message": str(exc)} if CONTENT_MODE == "full" else {}),
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
        **({"retrieval_decision": decision_payload} if CONTENT_MODE == "full" else {}),
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
    stream_state = stream_state if stream_state is not None else {}
    payload = {**request_payload, "stream": True, "stream_options": {"include_usage": True}}
    content_parts: list[str] = []
    pending_answer_parts: list[str] = []
    pending_answer_length = 0
    answer_started = False
    has_tool_calls = False
    tool_parts: dict[int, dict] = {}
    usage: dict = {}
    finish_reason: str | None = None
    response_id: str | None = None

    def suppress_pending_content() -> bool:
        if not stream_state.get("suppress_embedded_tool_json"):
            return False
        pending = "".join(pending_answer_parts).lstrip().lower()
        return pending.startswith("```json") or pending.startswith("{")

    async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
        response.raise_for_status()
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            response_id = response_id or chunk.get("id")
            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                content_parts.append(content)
                if answer_started:
                    stream_state["answer_emitted"] = True
                    await _notify(progress, {"event": "answer_delta", "delta": content})
                elif not has_tool_calls:
                    pending_answer_parts.append(content)
                    pending_answer_length += len(content)
                    if pending_answer_length >= 64:
                        if suppress_pending_content():
                            continue
                        required_disclosure = str(stream_state.get("required_disclosure") or "")
                        pending_text = "".join(pending_answer_parts)
                        if required_disclosure and not _has_knowledge_fallback_disclosure(pending_text):
                            await _notify(progress, {
                                "event": "answer_delta",
                                "delta": f"> {required_disclosure}\n\n",
                            })
                            stream_state["disclosure_emitted"] = True
                        answer_started = True
                        stream_state["answer_emitted"] = True
                        for part in pending_answer_parts:
                            await _notify(progress, {"event": "answer_delta", "delta": part})
                        pending_answer_parts.clear()
            for tool_delta in delta.get("tool_calls") or []:
                has_tool_calls = True
                pending_answer_parts.clear()
                index = int(tool_delta.get("index", 0))
                item = tool_parts.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if tool_delta.get("id"):
                    item["id"] = tool_delta["id"]
                function_delta = tool_delta.get("function") or {}
                if function_delta.get("name"):
                    item["function"]["name"] += function_delta["name"]
                if function_delta.get("arguments"):
                    item["function"]["arguments"] += function_delta["arguments"]
    assistant = {"role": "assistant", "content": "".join(content_parts)}
    if tool_parts:
        assistant["tool_calls"] = [tool_parts[index] for index in sorted(tool_parts)]
    elif not answer_started and not suppress_pending_content():
        if pending_answer_parts:
            required_disclosure = str(stream_state.get("required_disclosure") or "")
            pending_text = "".join(pending_answer_parts)
            if required_disclosure and not _has_knowledge_fallback_disclosure(pending_text):
                await _notify(progress, {
                    "event": "answer_delta",
                    "delta": f"> {required_disclosure}\n\n",
                })
                stream_state["disclosure_emitted"] = True
            stream_state["answer_emitted"] = True
        for part in pending_answer_parts:
            await _notify(progress, {"event": "answer_delta", "delta": part})
    return assistant, usage, response_id


def _retryable_model_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(exc, httpx.RequestError)


def _model_retry_delay(base_seconds: float, retry_number: int, exc: Exception) -> float:
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("retry-after")
        try:
            if retry_after is not None:
                return max(0.05, min(float(retry_after), 8.0))
        except ValueError:
            pass
    base = min(base_seconds * (2 ** max(0, retry_number - 1)), 8.0)
    return base + random.uniform(0, base * 0.2)


class ContextProtocolError(ValueError):
    def __init__(self, code: str, message: str, content: str = ""):
        super().__init__(message)
        self.code = code
        self.response_length = len(content)
        self.response_fingerprint = content_fingerprint(content) if content else None


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines or not re.fullmatch(r"```(?:json)?\s*", lines[0], re.IGNORECASE):
        return stripped
    if len(lines) < 3 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _context_json_arguments(assistant: dict) -> dict:
    content = assistant.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ContextProtocolError("empty_response", "上下文解析器必须返回一个 JSON 对象")
    cleaned = _strip_json_fence(content)
    try:
        arguments = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ContextProtocolError("invalid_json", "上下文解析结果不是合法 JSON", content) from exc
    if not isinstance(arguments, dict):
        raise ContextProtocolError("invalid_object", "上下文解析结果必须是 JSON 对象", content)
    required_fields = {
        "relation",
        "resolved_question",
        "topic_anchor",
        "target_message_ids",
        "confidence",
        "intent_hint",
    }
    missing_fields = required_fields - set(arguments)
    if missing_fields:
        raise ContextProtocolError(
            "missing_field",
            f"上下文解析结果缺少字段：{', '.join(sorted(missing_fields))}",
            content,
        )
    relation = arguments["relation"]
    intent_hint = arguments["intent_hint"]
    confidence = arguments["confidence"]
    target_ids = arguments["target_message_ids"]
    valid = (
        isinstance(relation, str)
        and relation in {"standalone", "followup", "correction", "recall"}
        and isinstance(arguments["resolved_question"], str)
        and bool(arguments["resolved_question"].strip())
        and isinstance(arguments["topic_anchor"], str)
        and isinstance(target_ids, list)
        and all(isinstance(item, int) and not isinstance(item, bool) for item in target_ids)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0 <= confidence <= 1
        and isinstance(intent_hint, str)
        and intent_hint in {"general_knowledge", "manufacturing_analysis", "unclear"}
    )
    if not valid:
        raise ContextProtocolError("invalid_field_type", "上下文解析结果字段类型或枚举值非法", content)
    return arguments


def _context_protocol_correction(error: ContextProtocolError) -> dict:
    return {
        "role": "user",
        "content": (
            "上一次上下文分类响应未通过协议校验"
            f"（{error.code}）。请重新返回一个符合最初契约的 JSON 对象；"
            "不要回答用户问题，不要省略必需字段。"
        ),
    }


async def _resolve_conversation_turn(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: ProgressCallback | None,
    direct_route: IntentRoute | None = None,
) -> tuple[ContextResolution, dict]:
    deterministic = resolve_question_context(question, history)
    if deterministic.applied or not settings.deepseek_api_key:
        return deterministic, {}
    if not history and (direct_route is None or direct_route.intent != "unknown"):
        return deterministic, {}

    await _notify(progress, {
        "event": "stage",
        "stage": "context",
        "message": "正在结合当前会话理解这条消息",
    })
    request_payload = {
        "model": settings.deepseek_model,
        "messages": build_contextualizer_messages(question, history),
        "temperature": 0,
        "response_format": CONTEXTUALIZER_RESPONSE_FORMAT,
        "max_tokens": 600,
    }
    endpoint = f"{settings.deepseek_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        attempt = 0
        protocol_failures = 0
        transport_failures = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            assistant: dict | None = None
            emit(
                "model_call_started",
                run_id,
                phase="contextualization",
                attempt=attempt,
                model=settings.deepseek_model,
                message_count=len(request_payload["messages"]),
                **({"request": request_payload} if CONTENT_MODE == "full" else {}),
            )
            try:
                assistant, usage, response_id = await _stream_completion(
                    client,
                    endpoint,
                    headers,
                    request_payload,
                    None,
                    {},
                )
                resolution = semantic_context_resolution(
                    question,
                    _context_json_arguments(assistant),
                    history,
                )
                if resolution.source == "fallback":
                    raise ContextProtocolError(
                        "invalid_message_id",
                        "上下文解析器引用了当前历史窗口之外的消息",
                        str(assistant.get("content") or ""),
                    )
            except Exception as exc:
                protocol_error = exc if isinstance(exc, ContextProtocolError) else None
                if protocol_error:
                    protocol_failures += 1
                    retryable = True
                    will_retry = protocol_failures < 2
                else:
                    retryable = _retryable_model_error(exc)
                    if retryable:
                        transport_failures += 1
                    will_retry = retryable and transport_failures <= settings.model_max_retries
                emit(
                    "model_call_finished",
                    run_id,
                    status="error",
                    phase="contextualization",
                    attempt=attempt,
                    model=settings.deepseek_model,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    error_type=type(exc).__name__,
                    retryable=retryable,
                    will_retry=will_retry,
                    protocol_error_code=protocol_error.code if protocol_error else None,
                    response_length=protocol_error.response_length if protocol_error else None,
                    response_fingerprint=protocol_error.response_fingerprint if protocol_error else None,
                    **({
                        "error_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "response": assistant,
                    } if CONTENT_MODE == "full" else {}),
                )
                if will_retry:
                    if protocol_error:
                        request_payload["messages"] = [
                            *request_payload["messages"],
                            _context_protocol_correction(protocol_error),
                        ]
                    else:
                        await asyncio.sleep(
                            _model_retry_delay(settings.model_retry_base_seconds, transport_failures, exc)
                        )
                    continue
                emit(
                    "question_context_resolution_failed",
                    run_id,
                    error_type=type(exc).__name__,
                )
                await _notify(progress, {
                    "event": "stage",
                    "stage": "context",
                    "message": "未能可靠恢复上文指代",
                })
                fallback_route = direct_route or route_question(question)
                if history and (
                    fallback_route.intent == "unknown" or fallback_route.clarification_needed
                ):
                    return context_clarification_resolution(
                        question,
                        history,
                        protocol_error.code if protocol_error else type(exc).__name__,
                    ), {}
                return unresolved_context(question, "fallback"), {}

            emit(
                "model_call_finished",
                run_id,
                status="success",
                phase="contextualization",
                attempt=attempt,
                model=settings.deepseek_model,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason="stop",
                response_id=response_id,
                **({"response": assistant, "context_resolution": resolution.to_dict()} if CONTENT_MODE == "full" else {}),
            )
            emit(
                "question_context_classified",
                run_id,
                relation=resolution.relation,
                strategy=resolution.strategy,
                applied=resolution.applied,
                confidence=resolution.confidence,
                original_length=len(question),
                resolved_length=len(resolution.resolved_question),
            )
            await _notify(progress, {
                "event": "stage",
                "stage": "context",
                "message": (
                    "已结合上文恢复当前消息的完整目标"
                    if resolution.applied
                    else "未可靠关联到上文，将按当前消息独立判断"
                    if resolution.relation != "standalone"
                    else "已确认当前消息是独立问题"
                ),
                "context_resolution": resolution.to_dict(),
            })
            return resolution, usage

    return unresolved_context(question, "fallback"), {}


async def _run_agent_impl(
    question: str,
    history: list[dict] | None,
    run_id: str,
    progress: ProgressCallback | None = None,
) -> dict:
    settings = effective_agent_settings(get_settings())
    direct_route = route_question(question)
    context_resolution, context_usage = await _resolve_conversation_turn(
        question,
        history,
        settings,
        run_id,
        progress,
        direct_route,
    )
    analysis_question = context_resolution.resolved_question
    if context_resolution.applied:
        emit(
            "question_context_resolved",
            run_id,
            strategy=context_resolution.strategy,
            original_length=len(question),
            resolved_length=len(analysis_question),
        )
        if context_resolution.source == "deterministic":
            await _notify(progress, {
                "event": "stage",
                "stage": "context",
                "message": "已根据上条回答中的选项恢复分析目标",
                "context_resolution": context_resolution.to_dict(),
            })
    base_route = (
        route_question("介绍一下你自己")
        if context_resolution.strategy in {"semantic_recall", "context_clarification"}
        else route_question(analysis_question)
        if context_resolution.applied
        else direct_route
    )
    intent_route = apply_semantic_intent_hint(
        base_route,
        context_resolution.intent_hint,
        context_resolution.confidence,
        context_applied=context_resolution.applied,
    )
    if intent_route.intent != base_route.intent:
        emit(
            "semantic_intent_hint_applied",
            run_id,
            from_intent=base_route.intent,
            to_intent=intent_route.intent,
            intent_hint=context_resolution.intent_hint,
            confidence=context_resolution.confidence,
            relation=context_resolution.relation,
        )
    route_payload = intent_route.to_dict()
    emit(
        "intent_routed",
        run_id,
        intent=intent_route.intent,
        confidence=intent_route.confidence,
        process_steps=list(intent_route.process_steps),
        equipment_ids=list(intent_route.equipment_ids),
        scope_resolution=route_payload["scope_resolution"],
        time_range=route_payload["time_range"],
        data_requirements=list(intent_route.data_requirements),
        risk_level=intent_route.risk_level,
        clarification_needed=intent_route.clarification_needed,
    )
    await _notify(progress, {
        "event": "stage",
        "stage": "routing",
        "message": _routing_progress_message(intent_route),
        "route": route_payload,
    })
    playbook_selection = select_playbook(intent_route)
    playbook_payload = playbook_selection.to_dict()
    selected_playbook = playbook_selection.selected_playbook
    emit(
        "playbook_selected",
        run_id,
        status=playbook_selection.status,
        route_intent=intent_route.intent,
        playbook_id=selected_playbook.playbook_id if selected_playbook else None,
        playbook_version=selected_playbook.playbook_version if selected_playbook else None,
        candidate_playbooks=[item.playbook_id for item in playbook_selection.candidate_playbooks],
    )
    await _notify(progress, {
        "event": "stage",
        "stage": "playbook",
        "message": _playbook_progress_message(playbook_selection),
        "playbook": playbook_payload,
    })
    execution_plan = create_execution_plan(analysis_question, intent_route, playbook_selection)
    plan_payload = execution_plan.to_dict()
    emit(
        "execution_plan_created",
        run_id,
        plan_id=execution_plan.plan_id,
        status=execution_plan.status,
        planner_version=execution_plan.planner_version,
        playbook_id=execution_plan.playbook_id,
        playbook_version=execution_plan.playbook_version,
        primary_scope_type=execution_plan.scope_contract.primary_scope_type,
        primary_scope_ids=list(execution_plan.scope_contract.primary_scope_ids),
        context_only_tools=list(execution_plan.scope_contract.context_only_tools),
        step_count=len(execution_plan.steps),
        required_evidence_count=len(execution_plan.required_evidence_ids),
        planned_tool_calls=execution_plan.budget.planned_tool_calls,
        max_tool_calls=execution_plan.budget.max_tool_calls,
        missing_inputs=list(execution_plan.missing_inputs),
    )
    await _notify(progress, {
        "event": "stage",
        "stage": "plan",
        "message": _plan_progress_message(execution_plan),
        "plan": plan_payload,
    })
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
        )
        result["mode"] = "clarification"
        result["model"] = settings.deepseek_model if context_usage else "deterministic-router"
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
        )
        result["model"] = settings.deepseek_model if context_usage else "deterministic-router"
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
    if not settings.deepseek_api_key:
        await _notify(progress, {"event": "stage", "stage": "planning", "message": "正在使用本地规则规划分析路径"})
        result = _offline_answer(analysis_question, intent_route, playbook_selection, execution_plan, loop_guard)
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
    endpoint = f"{settings.deepseek_base_url}/chat/completions"
    total_usage = {
        key: int(context_usage.get(key, 0) or 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    applied_synthesis_reason: str | None = None
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
                model=settings.deepseek_model,
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
            "model": settings.deepseek_model,
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
        }

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
                "model": settings.deepseek_model,
                "messages": messages,
                "temperature": 0.15,
            }
            if intent_route.intent not in {"general_knowledge", "conversation"}:
                request_payload["tools"] = (
                    [SUBMIT_ANALYSIS_TOOL]
                    if synthesis_only and answer_contract.status == "required"
                    else TOOLS
                )
                request_payload["tool_choice"] = (
                    "none" if synthesis_only and answer_contract.status != "required" else "auto"
                )
                if synthesis_only and answer_contract.status == "required":
                    request_payload["max_tokens"] = 8192
            for attempt in range(1, settings.model_max_retries + 2):
                model_started = time.perf_counter()
                emit(
                    "model_call_started",
                    run_id,
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=settings.deepseek_model,
                    message_count=len(messages),
                    **({"request": request_payload} if CONTENT_MODE == "full" else {}),
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
                        {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
                        request_payload,
                        None if answer_contract.status == "required" else progress,
                        stream_state,
                    )
                except Exception as exc:
                    retryable = _retryable_model_error(exc) and not stream_state["answer_emitted"]
                    will_retry = retryable and attempt <= settings.model_max_retries
                    emit(
                        "model_call_finished",
                        run_id,
                        status="error",
                        iteration=iteration + 1,
                        attempt=attempt,
                        model=settings.deepseek_model,
                        duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                        error_type=type(exc).__name__,
                        retryable=retryable,
                        will_retry=will_retry,
                        answer_emitted=stream_state["answer_emitted"],
                        **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
                    )
                    if not will_retry:
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
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=settings.deepseek_model,
                    duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    finish_reason="tool_calls" if assistant.get("tool_calls") else "stop",
                    response_id=response_id,
                    **({"response": assistant} if CONTENT_MODE == "full" else {}),
                )
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
                    **({"arguments": arguments} if CONTENT_MODE == "full" else {}),
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
                        **({"arguments": arguments, "message": decision.message} if CONTENT_MODE == "full" else {}),
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
                    evidence_observations.append(EvidenceObservation(name, arguments, "success", result))
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
                        **({"result": result} if CONTENT_MODE == "full" else {}),
                    )
                    content = json.dumps({"ok": True, "data": result}, ensure_ascii=False, default=str)
                except Exception as exc:
                    loop_guard.record_result(name or "unknown", None, False)
                    evidence_observations.append(EvidenceObservation(name or "unknown", arguments, "error", error=str(exc)))
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
                        **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
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
                    model=settings.deepseek_model,
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
) -> dict:
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    first_token_at: float | None = None

    async def tracked_progress(event: dict) -> None:
        nonlocal first_token_at
        if event.get("event") == "answer_delta" and first_token_at is None:
            first_token_at = time.perf_counter()
        await _notify(progress, event)
    emit(
        "agent_run_started",
        run_id,
        question_length=len(question),
        question_fingerprint=content_fingerprint(question),
        history_messages=len(history or []),
        **({"question": question, "history": history or []} if CONTENT_MODE == "full" else {}),
    )
    await tracked_progress({"event": "run_started", "run_id": run_id, "message": "分析任务已创建"})
    try:
        result = await _run_agent_impl(question, history, run_id, tracked_progress)
        result["run_id"] = run_id
        result["status"] = "success"
        result["started_at"] = started_at
        result["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["first_token_ms"] = round((first_token_at - started) * 1000, 1) if first_token_at else None
        emit(
            "agent_run_finished",
            run_id,
            status="success",
            mode=result.get("mode", "unknown"),
            duration_ms=result["duration_ms"],
            tool_count=len(result.get("tool_trace", [])),
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
            **({
                "answer": result.get("answer"),
                "tool_trace": result.get("tool_trace", []),
                "sources": result.get("sources", []),
                "loop_guard": result.get("loop_guard", {}),
                "evidence_validation": result.get("evidence_validation", {}),
                "answer_contract": result.get("answer_contract", {}),
                "answer_synthesis": result.get("answer_synthesis", {}),
            } if CONTENT_MODE == "full" else {}),
        )
        return result
    except Exception as exc:
        await tracked_progress({"event": "run_failed", "run_id": run_id, "message": str(exc)})
        emit(
            "agent_run_finished",
            run_id,
            status="error",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            error_type=type(exc).__name__,
            **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
        )
        raise
