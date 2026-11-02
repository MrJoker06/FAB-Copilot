"""Unregistered native definitions for production reports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ...agent_runtime.tools.contracts import ToolExecutionContext
from ...agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from .contracts import (
    FabOverviewInput,
    ProcessPassRateInput,
    ProductionReportsPort,
    YieldTrendInput,
    production_report_scope,
    validate_fab_overview_output,
    validate_process_pass_rate_output,
    validate_yield_trend_output,
)
from .handler import (
    ProductionReportsDependencies,
    fab_overview_handler,
    process_pass_rate_handler,
    yield_trend_handler,
)

FAB_OVERVIEW_DEFINITION = ToolDefinition(
    "get_fab_overview",
    "1.0.0",
    "查询工厂批次、晶圆、良率、周期、hold和异常总览",
    FabOverviewInput,
    validate_fab_overview_output,
)
YIELD_TREND_DEFINITION = ToolDefinition(
    "get_yield_trend",
    "1.0.0",
    "按周查询良率和周期趋势，可按产品过滤",
    YieldTrendInput,
    validate_yield_trend_output,
)
PROCESS_PASS_RATE_DEFINITION = ToolDefinition(
    "get_process_pass_rate",
    "1.0.0",
    "查询指定制程的运行通过率",
    ProcessPassRateInput,
    validate_process_pass_rate_output,
)


def _prepare(
    input_value: FabOverviewInput | YieldTrendInput | ProcessPassRateInput,
    context: ToolExecutionContext[ProductionReportsDependencies],
) -> ToolPreparation[FabOverviewInput | YieldTrendInput | ProcessPassRateInput]:
    query = input_value.resolve(context.dependencies.today())
    cls = type(input_value)
    return ToolPreparation(
        cls(
            query.start.isoformat(),
            query.end.isoformat(),
            query.process_step,
            query.equipment_id,
        )
        if isinstance(input_value, ProcessPassRateInput)
        else cls(query.start.isoformat(), query.end.isoformat(), query.product)
        if isinstance(input_value, YieldTrendInput)
        else cls(query.start.isoformat(), query.end.isoformat()),
        production_report_scope(query, context.principal),
    )


def create_fab_overview_binding(
    port: ProductionReportsPort, *, today: Callable[[], date]
) -> ToolBinding[FabOverviewInput, ProductionReportsDependencies, object]:
    return ToolBinding(
        FAB_OVERVIEW_DEFINITION,
        fab_overview_handler,
        ProductionReportsDependencies(port, today),
        _prepare,
    )


def create_yield_trend_binding(
    port: ProductionReportsPort, *, today: Callable[[], date]
) -> ToolBinding[YieldTrendInput, ProductionReportsDependencies, object]:
    return ToolBinding(
        YIELD_TREND_DEFINITION,
        yield_trend_handler,
        ProductionReportsDependencies(port, today),
        _prepare,
    )


def create_process_pass_rate_binding(
    port: ProductionReportsPort, *, today: Callable[[], date]
) -> ToolBinding[ProcessPassRateInput, ProductionReportsDependencies, object]:
    return ToolBinding(
        PROCESS_PASS_RATE_DEFINITION,
        process_pass_rate_handler,
        ProductionReportsDependencies(port, today),
        _prepare,
    )
