from __future__ import annotations

import json
import re
from typing import Any

from fab_contracts import IdentityContext
from fab_core import DataGateway


class FabAnalysisAgent:
    """Small deterministic tool router used until a model provider is configured.

    The runtime deliberately depends on the DataGateway port, so replacing this
    router with an LLM tool loop cannot bypass Data MCP or its SQL guard.
    """

    def __init__(self, gateway: DataGateway) -> None:
        self._gateway = gateway

    async def analyze(self, message: str, identity: IdentityContext) -> dict[str, Any]:
        tool_calls = self._route(message)
        results = []
        for tool, arguments in tool_calls:
            result = await self._gateway.call_tool(tool, arguments, identity)
            results.append(result)
        return {
            "answer": self._answer(message, results),
            "mode": "deterministic-mcp",
            "tool_trace": [
                {
                    "tool": result.tool,
                    "status": "success",
                    "rows": result.row_count,
                    "truncated": result.truncated,
                }
                for result in results
            ],
            "evidence": [{"tool": result.tool, "data": result.data} for result in results],
        }

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
        match = re.search(r"\b(CVD|ETCH|LITHO|CMP|PVD|IMPLANT|DIFFUSION)\b", message.upper())
        return match.group(1) if match else "CVD"

    @staticmethod
    def _answer(message: str, results: list[Any]) -> str:
        sections = ["已通过受控 Data MCP 查询制造数据。"]
        for result in results:
            data = result.data
            if result.tool == "get_fab_overview" and isinstance(data, dict):
                sections.append(
                    "工厂总览：完成批次 {lots}，平均良率 {yield_pct}%，平均周期 {cycle} 小时，"
                    "异常 {excursions} 项。".format(
                        lots=data.get("lots", 0),
                        yield_pct=data.get("yield_pct", "-"),
                        cycle=data.get("avg_cycle_hours", "-"),
                        excursions=data.get("excursions", 0),
                    )
                )
            elif isinstance(data, list):
                preview = data[:3]
                sections.append(
                    f"{result.tool} 返回 {len(data)} 条记录；前三条证据："
                    f"{json.dumps(preview, ensure_ascii=False, default=str)}"
                )
            else:
                sections.append(f"{result.tool}：{json.dumps(data, ensure_ascii=False, default=str)[:1200]}")
        sections.append(f"分析问题：{message.strip()}")
        sections.append("当前结论仅用于排查线索，根因仍需结合批次、设备和工程验证确认。")
        return "\n\n".join(sections)
