from __future__ import annotations

from typing import Any

DATA_TOOL_NAMES = (
    "get_fab_overview",
    "get_yield_trend",
    "get_equipment_health",
    "get_equipment_productivity",
    "get_process_capability",
    "get_defect_pareto",
    "get_recent_excursions",
    "get_sensor_summary",
    "query_manufacturing_data",
)


def tool_definitions() -> list[dict[str, Any]]:
    date_properties = {
        "start": {"type": "string", "format": "date"},
        "end": {"type": "string", "format": "date"},
    }
    definitions: dict[str, tuple[str, dict[str, Any]]] = {
        "get_fab_overview": ("查询工厂批次、良率、周期和异常总览", date_properties),
        "get_yield_trend": ("查询良率和周期趋势", {**date_properties, "product": {"type": "string"}}),
        "get_equipment_health": ("查询设备健康和异常", date_properties),
        "get_equipment_productivity": ("查询 SEMI E10 设备状态占比", date_properties),
        "get_process_capability": (
            "查询各设备制程能力",
            {**date_properties, "process_step": {"type": "string"}},
        ),
        "get_defect_pareto": ("查询缺陷 Pareto", {**date_properties, "limit": {"type": "integer"}}),
        "get_recent_excursions": (
            "查询近期异常批次",
            {**date_properties, "process_step": {"type": "string"}, "limit": {"type": "integer"}},
        ),
        "get_sensor_summary": (
            "查询传感器摘要",
            {
                **date_properties,
                "process_step": {"type": "string"},
                "equipment_id": {"type": "string"},
                "signal_name": {"type": "string"},
            },
        ),
        "query_manufacturing_data": ("执行受控只读制造数据查询", {"sql": {"type": "string"}}),
    }
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "additionalProperties": False,
                },
            },
        }
        for name, (description, properties) in definitions.items()
    ]
