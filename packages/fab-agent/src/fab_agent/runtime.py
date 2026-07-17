from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from fab_contracts import IdentityContext, ToolResult
from fab_core import DataGateway

from .tools import DATA_TOOL_NAMES, tool_definitions


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout_seconds: float = 60.0
    max_tool_rounds: int = 6


SYSTEM_PROMPT = f"""你是晶圆厂制造分析助手 Fab Copilot。当前日期是 {date.today().isoformat()}。

回答规则：
1. 使用简洁中文，先回答用户真正提出的问题，再补充证据和限制。
2. 自我介绍、问候、能力说明等普通对话不要调用制造数据工具。
3. 涉及良率、设备、批次、缺陷、异常、制程能力或传感器时，必须先调用合适的工具，不得猜测数字。
4. 工具返回值是分析证据，不要原样输出 JSON；应提炼为人类可读的结论。
5. 区分事实、推断和建议，不把相关性表述成因果关系。
6. 停机、报废或配方变更等高风险建议必须要求工程师复核。
7. 只能使用提供的只读工具，不得请求或生成写库操作。
"""


class FabAnalysisAgent:
    """Orchestrate conversational answers and controlled Data MCP tools."""

    def __init__(self, gateway: DataGateway, model: ModelConfig | None = None) -> None:
        self._gateway = gateway
        self._model = model or ModelConfig()

    async def analyze(self, message: str, identity: IdentityContext) -> dict[str, Any]:
        direct_answer = self._direct_answer(message)
        if direct_answer is not None:
            return {
                "answer": direct_answer,
                "mode": "direct",
                "tool_trace": [],
                "evidence": [],
            }

        if self._model.api_key:
            try:
                return await self._analyze_with_model(message, identity)
            except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                # A model outage must not turn the UI into an empty response. The
                # typed MCP router remains available as an explicit local fallback.
                return await self._analyze_deterministically(message, identity, fallback=True)
        return await self._analyze_deterministically(message, identity)

    async def _analyze_with_model(self, message: str, identity: IdentityContext) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]
        trace: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        endpoint = f"{self._model.base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=self._model.timeout_seconds) as client:
            for round_number in range(1, self._model.max_tool_rounds + 1):
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._model.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model.model,
                        "messages": messages,
                        "tools": tool_definitions(),
                        "tool_choice": "auto",
                        "temperature": 0.15,
                    },
                )
                response.raise_for_status()
                assistant = response.json()["choices"][0]["message"]
                content = assistant.get("content") or ""
                tool_calls = assistant.get("tool_calls") or []
                messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        **({"tool_calls": tool_calls} if tool_calls else {}),
                    }
                )

                if not tool_calls:
                    answer = content.strip()
                    if not answer:
                        raise ValueError("model returned an empty answer")
                    return {
                        "answer": answer,
                        "mode": "model-mcp",
                        "tool_trace": trace,
                        "evidence": evidence,
                    }

                for index, tool_call in enumerate(tool_calls):
                    function = tool_call.get("function") or {}
                    tool_name = str(function.get("name") or "")
                    if tool_name not in DATA_TOOL_NAMES:
                        raise ValueError(f"model requested unsupported tool: {tool_name}")
                    raw_arguments = function.get("arguments") or "{}"
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    if not isinstance(arguments, dict):
                        raise ValueError("model tool arguments must be an object")

                    result = await self._gateway.call_tool(tool_name, arguments, identity)
                    trace.append(self._trace(result))
                    evidence.append({"tool": result.tool, "data": result.data})
                    tool_call_id = str(tool_call.get("id") or f"call-{round_number}-{index}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": self._model_tool_content(result),
                        }
                    )

        # If the provider keeps requesting tools, return a readable answer from
        # the evidence already collected instead of exposing protocol payloads.
        return {
            "answer": self._answer(message, self._results_from_evidence(evidence, identity.request_id)),
            "mode": "model-mcp-fallback",
            "tool_trace": trace,
            "evidence": evidence,
        }

    async def _analyze_deterministically(
        self, message: str, identity: IdentityContext, fallback: bool = False
    ) -> dict[str, Any]:
        results = []
        for tool, arguments in self._route(message):
            results.append(await self._gateway.call_tool(tool, arguments, identity))
        return {
            "answer": self._answer(message, results),
            "mode": "deterministic-mcp-fallback" if fallback else "deterministic-mcp",
            "tool_trace": [self._trace(result) for result in results],
            "evidence": [{"tool": result.tool, "data": result.data} for result in results],
        }

    @staticmethod
    def _direct_answer(message: str) -> str | None:
        normalized = re.sub(r"[\s，。！？,.!?]+", "", message.lower())
        manufacturing_terms = (
            "良率",
            "yield",
            "设备",
            "equipment",
            "机台",
            "异常",
            "excursion",
            "告警",
            "缺陷",
            "defect",
            "pareto",
            "cpk",
            "制程能力",
            "capability",
            "传感器",
            "sensor",
            "fdc",
            "oee",
            "e10",
            "生产率",
        )
        if any(term in normalized for term in manufacturing_terms):
            return None
        introduction_phrases = (
            "介绍一下你自己",
            "自我介绍",
            "你是谁",
            "你是什么",
            "你能做什么",
            "有什么功能",
            "help",
            "hello",
            "你好",
        )
        if not any(phrase in normalized for phrase in introduction_phrases):
            return None
        return (
            "我是 Fab Copilot，一名面向晶圆厂制造分析的只读助手。\n\n"
            "我可以通过受控 Data MCP 查询良率趋势、设备健康、SEMI E10 生产率、"
            "制程能力 Cpk、缺陷 Pareto、异常批次和传感器摘要，并把结果整理成可读结论。"
            "我不会修改生产数据库；涉及停机、报废或配方变更时，会要求工程师复核。\n\n"
            "你可以问我：『最近 30 天 CVD-02 的能力变化与可能原因』。"
        )

    def _route(self, message: str) -> list[tuple[str, dict[str, Any]]]:
        normalized = message.lower()
        date_args = self._date_arguments(message)
        if any(word in normalized for word in ("cpk", "制程能力", "capability")):
            return [("get_process_capability", {**date_args, "process_step": self._process_step(message)})]
        if any(word in normalized for word in ("传感器", "sensor", "fdc")):
            return [("get_sensor_summary", {**date_args, "process_step": self._process_step(message)})]
        if any(word in normalized for word in ("缺陷", "defect", "pareto")):
            return [("get_defect_pareto", {**date_args, "limit": 10})]
        if any(word in normalized for word in ("设备效率", "oee", "e10", "生产率")):
            return [("get_equipment_productivity", date_args)]
        if any(word in normalized for word in ("设备", "equipment", "机台")):
            return [("get_equipment_health", date_args)]
        if any(word in normalized for word in ("异常", "excursion", "告警")):
            return [("get_recent_excursions", {**date_args, "limit": 12})]
        if any(word in normalized for word in ("良率", "yield", "趋势")):
            return [("get_yield_trend", date_args)]
        return [
            ("get_fab_overview", date_args),
            ("get_recent_excursions", {**date_args, "limit": 5}),
        ]

    @staticmethod
    def _date_arguments(message: str) -> dict[str, str]:
        dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", message)
        if len(dates) >= 2:
            return {"start": dates[0], "end": dates[1]}
        return {}

    @staticmethod
    def _process_step(message: str) -> str:
        match = re.search(
            r"\b(CVD|ETCH|LITHO|CMP|PVD|IMPLANT|DIFFUSION|CLEAN|METROLOGY)\b",
            message.upper(),
        )
        return match.group(1) if match else "CVD"

    @staticmethod
    def _trace(result: ToolResult) -> dict[str, Any]:
        return {
            "tool": result.tool,
            "status": "success",
            "rows": result.row_count,
            "truncated": result.truncated,
        }

    @staticmethod
    def _model_tool_content(result: ToolResult) -> str:
        content = json.dumps(
            {"tool": result.tool, "row_count": result.row_count, "data": result.data},
            ensure_ascii=False,
            default=str,
        )
        return content[:40_000]

    @staticmethod
    def _results_from_evidence(evidence: list[dict[str, Any]], request_id: str) -> list[ToolResult]:
        return [
            ToolResult(
                tool=item["tool"],
                data=item["data"],
                row_count=len(item["data"]) if isinstance(item["data"], list) else 1,
                request_id=request_id,
            )
            for item in evidence
        ]

    @classmethod
    def _answer(cls, message: str, results: list[ToolResult]) -> str:
        sections = ["已通过受控 Data MCP 查询制造数据。"]
        for result in results:
            sections.append(cls._summarize_result(result))
        sections.append("以上是数据事实；根因判断仍需结合批次、设备状态和工程验证。")
        return "\n\n".join(sections)

    @classmethod
    def _summarize_result(cls, result: ToolResult) -> str:
        data = result.data
        if result.tool == "get_fab_overview" and isinstance(data, dict):
            return (
                "工厂总览：完成批次 {lots}，平均良率 {yield_pct}%，平均周期 {cycle} 小时，"
                "异常 {excursions} 项。".format(
                    lots=data.get("lots", 0),
                    yield_pct=data.get("yield_pct", "-"),
                    cycle=data.get("avg_cycle_hours", "-"),
                    excursions=data.get("excursions", 0),
                )
            )
        if not isinstance(data, list):
            return f"{cls._tool_label(result.tool)}：查询已完成。"
        if not data:
            return f"{cls._tool_label(result.tool)}：指定条件下未查到记录。"

        if result.tool == "get_recent_excursions":
            rows = [
                "、".join(
                    str(value)
                    for value in (
                        row.get("run_time"),
                        row.get("equipment_id"),
                        row.get("excursion_code"),
                        row.get("lot_id"),
                    )
                    if value not in (None, "")
                )
                for row in data[:3]
            ]
            return f"近期异常共 {len(data)} 条。最新记录：\n- " + "\n- ".join(rows)
        if result.tool == "get_defect_pareto":
            rows = [
                f"{row.get('defect_type', '-')}：{row.get('defect_count', row.get('count', '-'))}"
                for row in data[:5]
            ]
            return f"缺陷 Pareto 共 {len(data)} 类。前五项：" + "；".join(rows) + "。"
        if result.tool == "get_process_capability":
            ordered = sorted(data, key=lambda row: float(row.get("cpk") or 999))
            rows = [
                f"{row.get('equipment_id', '-')} {row.get('metric_name', '')} Cpk={row.get('cpk', '-')}"
                for row in ordered[:5]
            ]
            return f"制程能力共 {len(data)} 条。最低 Cpk 项：" + "；".join(rows) + "。"
        if result.tool == "get_equipment_health":
            risks = [row for row in data if row.get("health") not in (None, "Healthy")]
            selected = (risks or data)[:5]
            rows = [
                f"{row.get('equipment_id', '-')}（{row.get('health', '-')}，异常 {row.get('excursions', 0)}）"
                for row in selected
            ]
            return f"设备健康共 {len(data)} 台。优先关注：" + "；".join(rows) + "。"
        if result.tool == "get_yield_trend":
            first, last = data[0], data[-1]
            return (
                f"良率趋势共 {len(data)} 个周期：从 {first.get('yield_pct', '-')}%"
                f"变化到 {last.get('yield_pct', '-')}%，最新周期为 {last.get('week', '-')}。"
            )

        return f"{cls._tool_label(result.tool)}：返回 {len(data)} 条记录，已用于分析。"

    @staticmethod
    def _tool_label(tool: str) -> str:
        return {
            "get_fab_overview": "工厂总览",
            "get_yield_trend": "良率趋势",
            "get_equipment_health": "设备健康",
            "get_equipment_productivity": "设备生产率",
            "get_process_capability": "制程能力",
            "get_defect_pareto": "缺陷 Pareto",
            "get_recent_excursions": "近期异常",
            "get_sensor_summary": "传感器摘要",
            "query_manufacturing_data": "制造数据查询",
        }.get(tool, tool)
