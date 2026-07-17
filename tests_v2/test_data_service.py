from __future__ import annotations

import pytest
from fab_contracts import IdentityContext
from fab_core import DomainError
from fab_data_mcp.service import DataToolService


def test_data_tool_service_uses_temporary_readonly_databases(data_mcp_settings) -> None:
    service = DataToolService(data_mcp_settings)
    identity = IdentityContext(user_id="tester", request_id="req-12345678", scopes=("analytics:adhoc",))
    overview = service.call(
        "get_fab_overview",
        {"start": "2026-07-01", "end": "2026-07-17"},
        identity,
    )
    assert overview.data["lots"] == 2
    assert overview.data["held_lots"] == 1
    dashboard = service.call("get_dashboard", {}, identity)
    assert dashboard.data["overview"]["lots"] == 2
    assert dashboard.data["equipment"][0]["equipment_id"] == "CVD-02"
    assert set(dashboard.data) == {"overview", "yield_trend", "equipment", "defects", "excursions"}
    query = service.call("query_manufacturing_data", {"sql": "SELECT lot_id FROM lots"}, identity)
    assert query.row_count == 2
    assert query.request_id == identity.request_id


def test_ad_hoc_query_requires_explicit_scope(data_mcp_settings) -> None:
    service = DataToolService(data_mcp_settings)
    identity = IdentityContext(user_id="viewer", request_id="req-12345678")
    with pytest.raises(DomainError) as error:
        service.call("query_manufacturing_data", {"sql": "SELECT lot_id FROM lots"}, identity)
    assert error.value.status_code == 403
    assert error.value.error_code == "MCP_SCOPE_REQUIRED"
