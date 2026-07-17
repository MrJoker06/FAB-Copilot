from __future__ import annotations

from typing import Any

import httpx
import pytest
from fab_agent import FabAnalysisAgent, ModelConfig
from fab_contracts import IdentityContext, ToolResult


class GatewaySpy:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any], identity: IdentityContext
    ) -> ToolResult:
        self.calls.append((tool_name, arguments))
        data = self.responses.get(tool_name, [])
        return ToolResult(
            tool=tool_name,
            data=data,
            row_count=len(data) if isinstance(data, list) else 1,
            request_id=identity.request_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"ok": True}


class KnowledgeSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        self.calls.append((query, limit))
        return [
            {
                "source_type": "knowledge",
                "reference_id": "KB-1",
                "chunk_id": 1,
                "title": "CVD Control Plan",
                "source": "CP-CVD-01",
                "section": "Limits",
                "excerpt": "Thickness limits",
            }
        ]


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
        ("你好，请分析良率趋势", "get_yield_trend", None),
        ("查看 CLEAN 制程能力 Cpk", "get_process_capability", ("process_step", "CLEAN")),
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


@pytest.mark.asyncio
async def test_agent_answers_introduction_without_querying_manufacturing_data() -> None:
    gateway = GatewaySpy()
    agent = FabAnalysisAgent(gateway)
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")

    result = await agent.analyze("介绍一下你自己", identity)

    assert gateway.calls == []
    assert result["mode"] == "direct"
    assert "Fab Copilot" in result["answer"]
    assert "可以帮助你" in result["answer"]
    assert "Data MCP" not in result["answer"]


@pytest.mark.asyncio
async def test_agent_retrieves_governed_knowledge_for_root_cause_questions() -> None:
    gateway = GatewaySpy()
    knowledge = KnowledgeSpy()
    agent = FabAnalysisAgent(gateway, knowledge=knowledge)
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")

    result = await agent.analyze("CVD 膜厚漂移的潜在原因和处置建议", identity)

    assert gateway.calls == []
    assert knowledge.calls == [("CVD 膜厚漂移的潜在原因和处置建议", 6)]
    assert result["tool_trace"][0]["tool"] == "search_knowledge"
    assert result["sources"][0]["reference_id"] == "KB-1"
    assert "[KB-1]" in result["answer"]


@pytest.mark.asyncio
async def test_deterministic_fallback_summarizes_tool_rows_without_dumping_json() -> None:
    gateway = GatewaySpy(
        {
            "get_recent_excursions": [
                {
                    "run_time": "2026-07-13T23:53:08",
                    "lot_id": "L260711-09529",
                    "equipment_id": "CLEAN-02",
                    "excursion_code": "CLEAN-PARTICLE-HI",
                }
            ]
        }
    )
    agent = FabAnalysisAgent(gateway)
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")

    result = await agent.analyze("查看最近异常", identity)

    assert "CLEAN-02" in result["answer"]
    assert "CLEAN-PARTICLE-HI" in result["answer"]
    assert '{"run_time"' not in result["answer"]
    assert "Data MCP" not in result["answer"]


@pytest.mark.asyncio
async def test_model_tool_loop_returns_synthesized_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_defect_pareto",
                                        "arguments": '{"limit": 10}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "主要缺陷为 Particle，共 8 个；建议先核对来源设备。",
                        }
                    }
                ]
            },
        ]
    )

    async def fake_post(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
        requests.append(kwargs["json"])
        return httpx.Response(200, json=next(responses), request=httpx.Request("POST", "https://model.test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    gateway = GatewaySpy({"get_defect_pareto": [{"defect_type": "Particle", "defect_count": 8}]})
    agent = FabAnalysisAgent(
        gateway,
        ModelConfig(api_key="test-key", base_url="https://model.test", model="test-model"),
    )
    identity = IdentityContext(user_id="analyst", request_id="req-12345678")

    result = await agent.analyze(
        "继续分析主要来源",
        identity,
        history=[
            {"role": "user", "content": "近期主要缺陷是什么"},
            {"role": "assistant", "content": "上轮发现 Particle 居首。"},
        ],
    )

    assert result["mode"] == "model-mcp"
    assert gateway.calls == [("get_defect_pareto", {"limit": 10})]
    assert result["answer"].startswith("主要缺陷为 Particle")
    assert requests[0]["messages"][1:4] == [
        {"role": "user", "content": "近期主要缺陷是什么"},
        {"role": "assistant", "content": "上轮发现 Particle 居首。"},
        {"role": "user", "content": "继续分析主要来源"},
    ]


def test_runtime_model_configuration_masks_key_and_preserves_provider_settings() -> None:
    agent = FabAnalysisAgent(
        GatewaySpy(),
        ModelConfig(
            api_key="environment-secret",
            base_url="https://model.test",
            model="deepseek-v4-flash",
            api_key_source="environment",
        ),
    )

    initial = agent.public_model_config()
    updated = agent.configure_model("deepseek-v4-pro", "runtime-secret")

    assert initial["api_key_masked"].endswith("cret")
    assert "environment-secret" not in str(initial)
    assert updated["model"] == "deepseek-v4-pro"
    assert updated["api_key_source"] == "runtime"
    assert updated["api_key_masked"].endswith("cret")
