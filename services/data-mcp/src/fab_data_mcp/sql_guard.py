from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from fab_contracts import QueryResult
from fab_core import DomainError
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from .database import readonly_session
from .settings import DataMCPSettings

ALLOWED_TABLES = {
    "lots",
    "process_runs",
    "equipment_events",
    "defect_records",
    "sensor_readings",
    "equipment_state_intervals",
    "wafer_maps",
}
ALLOWED_SCHEMAS = {"", "main", "equipment", "quality"}
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile"}


@dataclass(frozen=True)
class GuardedQuery:
    sql: str
    tables: tuple[str, ...]


def guard_query(sql: str, max_rows: int = 100) -> GuardedQuery:
    normalized = sql.strip().rstrip(";").strip()
    if not normalized:
        raise DomainError("SQL_EMPTY", "SQL query must not be empty")
    try:
        statements = parse(normalized, read="sqlite")
    except ParseError as exc:
        raise DomainError("SQL_PARSE_ERROR", "SQL query could not be parsed") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise DomainError("SQL_NOT_READ_ONLY", "exactly one read-only query is required")
    expression = statements[0]
    forbidden_types = (
        exp.Alter,
        exp.Attach,
        exp.Command,
        exp.Create,
        exp.Delete,
        exp.Detach,
        exp.Drop,
        exp.Insert,
        exp.Merge,
        exp.Pragma,
        exp.Transaction,
        exp.Update,
        exp.Use,
    )
    if any(expression.find(node_type) is not None for node_type in forbidden_types):
        raise DomainError("SQL_NOT_READ_ONLY", "query contains a forbidden operation")

    cte_names = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in expression.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name in cte_names:
            continue
        schema_name = table.db.lower() if table.db else ""
        if schema_name not in ALLOWED_SCHEMAS or table_name not in ALLOWED_TABLES:
            raise DomainError("SQL_TABLE_FORBIDDEN", f"table is not available to the Agent: {table.sql()}")
        tables.add(table_name)
    if not tables:
        raise DomainError("SQL_TABLE_REQUIRED", "query must read at least one manufacturing table")

    for function in expression.find_all(exp.Func):
        function_names = {
            function.sql_name().lower(),  # type: ignore[no-untyped-call]
            str(getattr(function, "name", "")).lower(),
        }
        if function_names & DENIED_FUNCTIONS:
            raise DomainError("SQL_FUNCTION_FORBIDDEN", "query contains a forbidden function")

    rendered = expression.sql(dialect="sqlite")
    return GuardedQuery(
        sql=f"SELECT * FROM ({rendered}) AS guarded_query LIMIT {max_rows + 1}",
        tables=tuple(sorted(tables)),
    )


def execute_guarded_query(sql: str, settings: DataMCPSettings) -> tuple[QueryResult, tuple[str, ...]]:
    guarded = guard_query(sql, settings.max_query_rows)
    started = time.perf_counter()
    deadline = started + settings.query_timeout_seconds

    def progress() -> int:
        return int(time.perf_counter() >= deadline)

    with readonly_session(settings) as connection:
        connection.set_progress_handler(progress, 1_000)
        try:
            cursor = connection.execute(guarded.sql)
            fetched = cursor.fetchmany(settings.max_query_rows + 1)
            columns = tuple(item[0] for item in (cursor.description or ()))
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise DomainError(
                    "SQL_TIMEOUT",
                    "query exceeded the execution time limit",
                    status_code=408,
                    retryable=True,
                ) from exc
            raise DomainError("SQL_EXECUTION_ERROR", "query could not be executed") from exc
        finally:
            connection.set_progress_handler(None, 0)

    truncated = len(fetched) > settings.max_query_rows
    rows = tuple(dict(row) for row in fetched[: settings.max_query_rows])
    return (
        QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        ),
        guarded.tables,
    )
