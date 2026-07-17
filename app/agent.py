from __future__ import annotations

import asyncio
import inspect
import json
import random
import time
import traceback
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable

import httpx

from .audit import CONTENT_MODE, content_fingerprint, emit
from .config import get_settings
from .enterprise_data import enterprise_data_manifest, enterprise_fab_summary, query_enterprise_data
from .intent_router import IntentRoute, route_question, routing_system_message
from .model_registry import effective_agent_settings
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
2. 涉及 SOP、规范、处置建议、工艺解释或历史经验时调用 search_knowledge。该工具会联合检索当前用户个人知识、正式知识与历史案例，引用时必须使用返回的 reference_id，格式为 [来源 PERSONAL-编号]、[来源 KB-数字] 或 [来源 CASE-编号]。
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
    {"type": "function", "function": {"name": "get_equipment_health", "description": "查询设备运行数、异常数、缺陷密度、停机和健康状态", "parameters": _schema(DATE_PROPERTIES)}},
    {"type": "function", "function": {"name": "get_equipment_productivity", "description": "按SEMI E10状态查询设备生产、待机、工程和停机时间占比", "parameters": _schema(DATE_PROPERTIES)}},
    {"type": "function", "function": {"name": "get_process_capability", "description": "按站点关键量测和规格限查询各设备Cpk", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}})}},
    {"type": "function", "function": {"name": "get_defect_pareto", "description": "查询缺陷类型Pareto和受影响批次数", "parameters": _schema({**DATE_PROPERTIES, "limit": {"type": "integer", "minimum": 1, "maximum": 25}})}},
    {"type": "function", "function": {"name": "get_recent_excursions", "description": "查询最近的制程异常批次及量测值，可按站点过滤", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}})}},
    {"type": "function", "function": {"name": "get_sensor_summary", "description": "按站点、设备或信号查询传感器均值、范围、缺失和异常标记", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)}, "equipment_id": {"type": "string"}, "signal_name": {"type": "string"}})}},
    {"type": "function", "function": {"name": "search_knowledge", "description": "联合检索当前用户个人知识、厂内SOP、控制计划、分析方法与已验证历史案例。支持中英文制程术语召回，可按元数据过滤，返回可解释评分和reference_id", "parameters": _schema({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}, "process_step": {"type": "string", "enum": list(ANALYSIS_SCOPES)}, "equipment_id": {"type": "string"}, "defect_type": {"type": "string"}, "source_types": {"type": "array", "items": {"type": "string", "enum": ["personal", "knowledge", "case"]}}}, ["query"])}},
    {"type": "function", "function": {"name": "query_manufacturing_data", "description": "在固定报表不足时执行只读SQLite SELECT。只能访问白名单表，最多返回100行", "parameters": _schema({"sql": {"type": "string", "description": "单条SELECT语句，SQLite语法"}}, ["sql"])}},
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


def _offline_answer(question: str, intent_route: IntentRoute) -> dict:
    overview = fab_overview()
    equipment = equipment_health()
    risky = equipment[:3]
    lines = [
        "当前未配置可用的 DeepSeek API，因此返回本地规则分析。",
        f"最近90天共完成 {overview['lots']} 个批次，综合良率 {overview['yield_pct']}%，平均周期 {overview['avg_cycle_hours']} 小时。",
    ]
    if risky:
        names = "、".join(f"{row['equipment_id']}（{row['health']}，{row['excursions']}次异常）" for row in risky)
        lines.append(f"优先关注设备：{names}。")
    lines.append("配置根目录 .env 的 DEEPSEEK_API_KEY 后，可获得针对问题的多轮工具分析。")
    return {
        "answer": "\n\n".join(lines),
        "tool_trace": [
            {"tool": "get_fab_overview", "status": "local"},
            {"tool": "get_equipment_health", "status": "local"},
        ],
        "sources": [],
        "mode": "offline",
        "intent_route": intent_route.to_dict(),
    }


def _routing_progress_message(route: IntentRoute) -> str:
    if route.intent == "unknown":
        return "尚未识别明确分析目标，正在准备澄清问题"
    if route.intent == "ambiguous":
        return "识别到多个分析目标，正在确认优先路径"
    scope = "、".join(route.equipment_ids or route.process_steps)
    scope_text = f" · {scope}" if scope else ""
    return f"已识别为{route.intent_label}{scope_text}，正在限定数据范围"


async def _stream_completion(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict,
    request_payload: dict,
    progress: ProgressCallback | None,
    stream_state: dict[str, bool] | None = None,
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
    elif not answer_started:
        if pending_answer_parts:
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


async def _run_agent_impl(
    question: str,
    history: list[dict] | None,
    run_id: str,
    progress: ProgressCallback | None = None,
) -> dict:
    intent_route = route_question(question)
    route_payload = intent_route.to_dict()
    emit(
        "intent_routed",
        run_id,
        intent=intent_route.intent,
        confidence=intent_route.confidence,
        process_steps=list(intent_route.process_steps),
        equipment_ids=list(intent_route.equipment_ids),
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
    settings = effective_agent_settings(get_settings())
    if not settings.deepseek_api_key:
        await _notify(progress, {"event": "stage", "stage": "planning", "message": "正在使用本地规则规划分析路径"})
        result = _offline_answer(question, intent_route)
        for item in result["tool_trace"]:
            await _notify(progress, {"event": "tool_started", "tool": item["tool"], "arguments": {}})
            await _notify(progress, {"event": "tool_finished", **item})
        await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "正在汇总本地分析结果"})
        await _notify(progress, {"event": "answer_delta", "delta": result["answer"]})
        result["model"] = "local-rules"
        result["usage"] = {}
        return result

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": routing_system_message(intent_route)},
    ]
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:4000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    trace: list[dict] = []
    sources: dict[str, dict] = {}
    endpoint = f"{settings.deepseek_base_url}/chat/completions"
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        for iteration in range(6):
            await _notify(progress, {
                "event": "stage",
                "stage": "planning",
                "iteration": iteration + 1,
                "message": "正在理解问题并规划分析路径" if iteration == 0 else "正在结合工具结果判断是否继续，并组织结论",
            })
            request_payload = {
                "model": settings.deepseek_model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.15,
            }
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
                stream_state = {"answer_emitted": False}
                try:
                    assistant, usage, response_id = await _stream_completion(
                        client,
                        endpoint,
                        {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
                        request_payload,
                        progress,
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
                return {
                    "answer": assistant.get("content") or "分析完成，但模型没有返回文字。",
                    "tool_trace": trace,
                    "sources": list(sources.values()),
                    "mode": "deepseek",
                    "model": settings.deepseek_model,
                    "usage": total_usage,
                    "intent_route": route_payload,
                }

            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                tool_started = time.perf_counter()
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    await _notify(progress, {"event": "tool_started", "tool": name, "arguments": arguments})
                    emit(
                        "tool_call_started",
                        run_id,
                        tool=name or "unknown",
                        tool_call_id=call.get("id"),
                        **({"arguments": arguments} if CONTENT_MODE == "full" else {}),
                    )
                    handler = TOOL_HANDLERS.get(name)
                    if handler is None:
                        raise ValueError(f"未知工具: {name}")
                    result = handler(**arguments)
                    if name == "search_knowledge":
                        for source in result:
                            sources[source["reference_id"]] = source
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
                    trace.append({"tool": name, "status": "error", "error": str(exc)})
                    await _notify(progress, {
                        "event": "tool_finished",
                        "tool": name,
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
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})

    answer = "工具调用达到上限。请缩小问题范围后重试。"
    await _notify(progress, {"event": "answer_delta", "delta": answer})
    return {
        "answer": answer,
        "tool_trace": trace,
        "sources": list(sources.values()),
        "mode": "deepseek",
        "model": settings.deepseek_model,
        "usage": total_usage,
        "intent_route": route_payload,
    }


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
            **({
                "answer": result.get("answer"),
                "tool_trace": result.get("tool_trace", []),
                "sources": result.get("sources", []),
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
