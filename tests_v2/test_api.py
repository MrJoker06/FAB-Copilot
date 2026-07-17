from __future__ import annotations

from typing import Any

import httpx
import pytest
from fab_api.app import create_app
from fab_api.settings import APISettings
from fab_contracts import IdentityContext, ToolResult


class FakeGateway:
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: IdentityContext,
    ) -> ToolResult:
        values: dict[str, Any] = {
            "get_dashboard": {
                "overview": {"lots": 2, "yield_pct": 91.0},
                "yield_trend": [{"week": "2026-27", "yield_pct": 91.0}],
                "equipment": [{"equipment_id": "CVD-01", "health": "Healthy"}],
                "defects": [{"defect_type": "Particle", "defect_count": 4}],
                "excursions": [{"lot_id": "LOT-2"}],
            },
            "get_fab_overview": {"lots": 2, "yield_pct": 91.0},
            "get_yield_trend": [{"week": "2026-27", "yield_pct": 91.0}],
            "get_equipment_health": [{"equipment_id": "CVD-01", "health": "Healthy"}],
            "get_defect_pareto": [{"defect_type": "Particle", "defect_count": 4}],
            "get_recent_excursions": [{"lot_id": "LOT-2"}],
            "get_process_capability": [{"equipment_id": "CVD-01", "cpk": 1.5}],
            "query_manufacturing_data": {"columns": ["lot_id"], "rows": [{"lot_id": "LOT-1"}]},
        }
        return ToolResult(
            tool=tool_name,
            data=values[tool_name],
            row_count=1,
            request_id=identity.request_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "ready"}


@pytest.mark.asyncio
async def test_v1_api_has_versioned_envelopes_and_request_ids(tmp_path) -> None:
    app = create_app(APISettings(project_dir=tmp_path), FakeGateway())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/v1/health/ready", headers={"X-Request-ID": "req-12345678"})
        dashboard = await client.get("/api/v1/reports/dashboard")
        capability = await client.get("/api/v1/reports/capability?process_step=cvd")
    assert health.status_code == 200
    assert health.headers["x-request-id"] == "req-12345678"
    assert health.json()["data"]["dependencies"]["data_mcp"]["ok"] is True
    assert dashboard.json()["data"]["overview"]["lots"] == 2
    assert capability.json()["data"][0]["cpk"] == 1.5
