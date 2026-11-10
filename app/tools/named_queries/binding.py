"""Unregistered definitions and bindings for manufacturing named queries."""

from __future__ import annotations

from datetime import date

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.tools.named_queries.contracts import (
    NAMED_QUERY_OUTPUT_SCHEMAS,
    TOOL_KINDS,
    EquipmentEventsInput,
    EquipmentExcursionsInput,
    LotQueryInput,
    NamedQueryPort,
    ProductYieldInput,
    named_query_scope,
    validate_named_query_output,
)
from app.tools.named_queries.handler import NamedQueryDependencies, NamedQueryInput, named_query_handler

_INPUTS = {
    "product_yield": ProductYieldInput,
    "equipment_events": EquipmentEventsInput,
    "equipment_excursions": EquipmentExcursionsInput,
    **{
        kind: LotQueryInput
        for kind in (
            "lot_identity",
            "lot_process_history",
            "lot_excursions",
            "lot_defects",
            "lot_wafer_maps",
        )
    },
}
_DESCRIPTIONS = {
    "get_product_yield_breakdown": "按产品查询指定日期范围内的技术节点良率、批次数和晶圆数，最多返回100行",
    "get_equipment_event_timeline": "按可选设备查询指定日期范围内的设备事件时间线，最多返回100行",
    "get_equipment_excursion_history": "按可选制程站点和设备查询指定日期范围内的设备关联制程异常，最多返回100行",
    "get_lot_identity": "按批次号查询批次身份、状态和良率信息，覆盖该批次全部历史，最多返回10行",
    "get_lot_process_history": "按批次号查询批次全部历史加工路线和设备记录，最多返回100行",
    "get_lot_excursion_history": "按批次号查询批次全部历史制程异常和量测记录，最多返回100行",
    "get_lot_defect_history": "按批次号查询批次全部历史缺陷和处置记录，最多返回100行",
    "get_lot_wafer_map_patterns": "按批次号查询批次全部历史晶圆图模式，最多返回100行",
}
_TITLES = {
    "get_product_yield_breakdown": "产品良率明细",
    "get_equipment_event_timeline": "设备事件时间线",
    "get_equipment_excursion_history": "设备异常历史",
    "get_lot_identity": "批次身份",
    "get_lot_process_history": "批次加工历史",
    "get_lot_excursion_history": "批次异常历史",
    "get_lot_defect_history": "批次缺陷历史",
    "get_lot_wafer_map_patterns": "批次晶圆图模式",
}
NAMED_QUERY_DEFINITIONS = {
    name: ToolDefinition(
        name,
        "1.0.0",
        _DESCRIPTIONS[name],
        _INPUTS[kind],
        lambda value, kind=kind: validate_named_query_output(kind, value),
        title=_TITLES[name],
        output_schema=NAMED_QUERY_OUTPUT_SCHEMAS[kind],
    )
    for name, kind in TOOL_KINDS.items()
}


def _prepare(
    input_value: NamedQueryInput, context: ToolExecutionContext[NamedQueryDependencies]
) -> ToolPreparation[NamedQueryInput]:
    query = input_value.resolve(context.dependencies.kind, context.dependencies.as_of)
    return ToolPreparation(input_value, named_query_scope(query, context.principal))


def create_named_query_binding(
    tool_name: str, port: NamedQueryPort, *, as_of: date
) -> ToolBinding:
    if tool_name not in TOOL_KINDS:
        raise ValueError("unknown named-query tool")
    return ToolBinding(
        NAMED_QUERY_DEFINITIONS[tool_name],
        named_query_handler,
        NamedQueryDependencies(port, TOOL_KINDS[tool_name], as_of),
        _prepare,
    )


def create_named_query_bindings(
    port: NamedQueryPort, *, as_of: date
) -> tuple[ToolBinding, ...]:
    return tuple(
        create_named_query_binding(name, port, as_of=as_of) for name in TOOL_KINDS
    )
