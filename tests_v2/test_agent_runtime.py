from __future__ import annotations

from typing import Any

import pytest
from fab_agent import FabAnalysisAgent
from fab_contracts import IdentityContext, ToolResult


class GatewaySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any], identity: IdentityContext
    ) -> ToolResult:
        self.calls.append((tool_name, arguments))
        return ToolResult(tool=tool_name, data=[], row_count=0, request_id=identity.request_id)

    async def health(self) -> dict[str, Any]:
        return {"ok": True}


@pytest.mark.parametrize(
    ("message", "expected", "argument"),
    [
        ("查看 ETCH 制程能力 Cpk", "get_process_capability", ("process_step", "ETCH")),
        ("分析 CVD 传感器 FDC", "get_sensor_summary", ("process_step", "CVD")),
        ("查看缺陷 Pareto", "get_defect_pareto", ("limit", 10)),
        ("设备效率 E10", "get_equipment_productivity", None),
        ("哪些机台设备有风险", "get_equipment_health", None),
        ("查看异常告警", "get_recent_excursions", ("limit", 12)),
        ("良率趋势", "get_yield_trend", None),
    ],
)
@pytest.mark.asyncio
async def test_agent_routes_manufacturing_questions_to_typed_mcp_tools(
    message: str,
    expected: str,
    argument: tuple[str, Any] | None,
) -> None:
    gateway = GatewaySpy()
    agent = FabAnalysisAgent(gateway)
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")
    result = await agent.analyze(message, identity)
    assert gateway.calls[0][0] == expected
    if argument is not None:
        assert gateway.calls[0][1][argument[0]] == argument[1]
    assert result["tool_trace"][0]["tool"] == expected


@pytest.mark.asyncio
async def test_agent_passes_explicit_date_range_to_mcp() -> None:
    gateway = GatewaySpy()
    agent = FabAnalysisAgent(gateway)
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")
    await agent.analyze("分析 2026-06-01 到 2026-07-01 的良率", identity)
    assert gateway.calls[0][1] == {"start": "2026-06-01", "end": "2026-07-01"}
