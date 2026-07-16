from __future__ import annotations

import pytest
from fab_core import DomainError
from fab_data_mcp.sql_guard import execute_guarded_query, guard_query


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM lots",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM simulation_scenarios",
        "SELECT * FROM lots; SELECT * FROM lots",
        "PRAGMA database_list",
        "SELECT load_extension('bad') FROM lots",
    ],
)
def test_sql_guard_rejects_writes_hidden_tables_and_escape_functions(sql: str) -> None:
    with pytest.raises(DomainError):
        guard_query(sql)


def test_sql_guard_allows_ctes_and_enforces_result_limit(data_mcp_settings) -> None:
    guarded = guard_query("WITH recent AS (SELECT * FROM lots) SELECT lot_id FROM recent")
    assert guarded.tables == ("lots",)
    result, tables = execute_guarded_query("SELECT lot_id, yield_rate FROM lots", data_mcp_settings)
    assert tables == ("lots",)
    assert result.row_count == 2
    assert result.columns == ("lot_id", "yield_rate")
