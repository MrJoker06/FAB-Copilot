from __future__ import annotations

import json
import time
import traceback
import uuid
from datetime import date
from typing import Any, Callable

import httpx

from .audit import CONTENT_MODE, content_fingerprint, emit
from .config import get_settings
from .rag import search_knowledge
from .reports import (
    defect_pareto,
    equipment_health,
    fab_overview,
    process_capability,
    recent_excursions,
    safe_select,
    yield_trend,
)


SYSTEM_PROMPT = f"""你是晶圆厂制造分析 Agent「Fab Copilot」。你的职责是基于工具返回的真实数据回答问题。

当前日期是 {date.today().isoformat()}。用户说“最近N天”时，以这个日期为结束日期准确计算起始日期；未指定时间范围时使用最近90天。

规则：
1. 涉及数字、趋势、设备、批次时必须先调用数据工具，不得猜测。
2. 涉及 SOP、规范、处置建议或工艺解释时调用 search_knowledge，并使用工具返回的 chunk_id 标注为 [来源 chunk_id]。
3. 先给结论，再给证据；区分事实、推断和建议。不要宣称相关性就是因果性。
4. 报告百分比时说明时间范围和样本量。若数据不足，明确说明。
5. 不执行写库操作。高风险建议（停机、报废、配方变更）必须要求工程师复核。
6. 回答使用简洁中文，日期使用 YYYY-MM-DD。
7. 本演示系统的制程能力判定统一使用 Cpk 1.33：低于 1.33 为能力不足，1.33 至 1.67 为观察区间，高于或等于 1.67 为稳定；不得自行改写阈值。

数据库字段提示：
- lots: lot_id, product, technology_nm, route, priority, start_time, complete_time, status, wafer_count, good_wafers, yield_rate(0-1), cycle_time_hours, hold_hours
- process_runs: lot_id, process_step, equipment_id, run_time, temperature_c, pressure_torr, duration_sec, thickness_nm, uniformity_pct, defect_density, pass_flag, excursion_code
- equipment_events: equipment_id, event_time, event_type, duration_minutes, severity, reason
- defect_records: lot_id, detected_time, process_step, defect_type, count, disposition
"""


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


DATE_PROPERTIES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}

TOOLS = [
    {"type": "function", "function": {"name": "get_fab_overview", "description": "查询工厂批次、晶圆、良率、周期、hold和异常总览", "parameters": _schema(DATE_PROPERTIES)}},
    {"type": "function", "function": {"name": "get_yield_trend", "description": "按周查询良率和周期趋势，可按产品过滤", "parameters": _schema({**DATE_PROPERTIES, "product": {"type": "string", "description": "产品名，如 Nova-P1"}})}},
    {"type": "function", "function": {"name": "get_equipment_health", "description": "查询设备运行数、异常数、缺陷密度、停机和健康状态", "parameters": _schema(DATE_PROPERTIES)}},
    {"type": "function", "function": {"name": "get_process_capability", "description": "查询制程设备能力。CVD计算膜厚Cpk，其他站点计算缺陷密度单边Cpk", "parameters": _schema({**DATE_PROPERTIES, "process_step": {"type": "string", "enum": ["LITHO", "ETCH", "CVD", "CMP"]}})}},
    {"type": "function", "function": {"name": "get_defect_pareto", "description": "查询缺陷类型Pareto和受影响批次数", "parameters": _schema({**DATE_PROPERTIES, "limit": {"type": "integer", "minimum": 1, "maximum": 25}})}},
    {"type": "function", "function": {"name": "get_recent_excursions", "description": "查询最近的制程异常批次及量测值", "parameters": _schema({**DATE_PROPERTIES, "limit": {"type": "integer", "minimum": 1, "maximum": 100}})}},
    {"type": "function", "function": {"name": "search_knowledge", "description": "检索厂内SOP、控制计划和故障处置知识，回答规范或建议前使用", "parameters": _schema({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"])}},
    {"type": "function", "function": {"name": "query_manufacturing_data", "description": "在固定报表不足时执行只读SQLite SELECT。只能访问白名单表，最多返回100行", "parameters": _schema({"sql": {"type": "string", "description": "单条SELECT语句，SQLite语法"}}, ["sql"])}},
]


TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "get_fab_overview": fab_overview,
    "get_yield_trend": yield_trend,
    "get_equipment_health": equipment_health,
    "get_process_capability": process_capability,
    "get_defect_pareto": defect_pareto,
    "get_recent_excursions": recent_excursions,
    "search_knowledge": search_knowledge,
    "query_manufacturing_data": safe_select,
}


def _offline_answer(question: str) -> dict:
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
    return {"answer": "\n\n".join(lines), "tool_trace": [{"tool": "get_fab_overview", "status": "local"}, {"tool": "get_equipment_health", "status": "local"}], "sources": [], "mode": "offline"}


async def _run_agent_impl(question: str, history: list[dict] | None, run_id: str) -> dict:
    settings = get_settings()
    if not settings.deepseek_api_key:
        return _offline_answer(question)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:4000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    trace: list[dict] = []
    sources: dict[int, dict] = {}
    endpoint = f"{settings.deepseek_base_url}/chat/completions"

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        for iteration in range(6):
            model_started = time.perf_counter()
            request_payload = {
                "model": settings.deepseek_model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.15,
            }
            emit(
                "model_call_started",
                run_id,
                iteration=iteration + 1,
                model=settings.deepseek_model,
                message_count=len(messages),
                **({"request": request_payload} if CONTENT_MODE == "full" else {}),
            )
            try:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
                    json=request_payload,
                )
                response.raise_for_status()
            except Exception as exc:
                emit(
                    "model_call_finished",
                    run_id,
                    status="error",
                    iteration=iteration + 1,
                    model=settings.deepseek_model,
                    duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                    error_type=type(exc).__name__,
                    **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
                )
                raise
            payload = response.json()
            usage = payload.get("usage") or {}
            emit(
                "model_call_finished",
                run_id,
                status="success",
                iteration=iteration + 1,
                model=settings.deepseek_model,
                duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=(payload.get("choices") or [{}])[0].get("finish_reason"),
                response_id=payload.get("id"),
                **({"response": payload} if CONTENT_MODE == "full" else {}),
            )
            assistant = payload["choices"][0]["message"]
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return {"answer": assistant.get("content") or "分析完成，但模型没有返回文字。", "tool_trace": trace, "sources": list(sources.values()), "mode": "deepseek"}

            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                tool_started = time.perf_counter()
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
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
                            sources[source["chunk_id"]] = source
                    row_count = len(result) if isinstance(result, list) else 1
                    trace.append({"tool": name, "arguments": arguments, "status": "ok", "rows": row_count})
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="success",
                        tool=name,
                        duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
                        rows=row_count,
                        **({"result": result} if CONTENT_MODE == "full" else {}),
                    )
                    content = json.dumps({"ok": True, "data": result}, ensure_ascii=False, default=str)
                except Exception as exc:
                    trace.append({"tool": name, "status": "error", "error": str(exc)})
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

    return {"answer": "工具调用达到上限。请缩小问题范围后重试。", "tool_trace": trace, "sources": list(sources.values()), "mode": "deepseek"}


async def run_agent(question: str, history: list[dict] | None = None) -> dict:
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    emit(
        "agent_run_started",
        run_id,
        question_length=len(question),
        question_fingerprint=content_fingerprint(question),
        history_messages=len(history or []),
        **({"question": question, "history": history or []} if CONTENT_MODE == "full" else {}),
    )
    try:
        result = await _run_agent_impl(question, history, run_id)
        result["run_id"] = run_id
        emit(
            "agent_run_finished",
            run_id,
            status="success",
            mode=result.get("mode", "unknown"),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            tool_count=len(result.get("tool_trace", [])),
            source_count=len(result.get("sources", [])),
            **({
                "answer": result.get("answer"),
                "tool_trace": result.get("tool_trace", []),
                "sources": result.get("sources", []),
            } if CONTENT_MODE == "full" else {}),
        )
        return result
    except Exception as exc:
        emit(
            "agent_run_finished",
            run_id,
            status="error",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            error_type=type(exc).__name__,
            **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
        )
        raise
