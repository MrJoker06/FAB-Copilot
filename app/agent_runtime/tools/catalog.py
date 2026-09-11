"""Stable model-facing Agent tool catalog."""

from __future__ import annotations

from ...answer_synthesizer import SUBMIT_ANALYSIS_TOOL
from ...manufacturing.processes import ANALYSIS_SCOPES, MANUFACTURING_STEPS


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


DATE_PROPERTIES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_enterprise_data_manifest",
            "description": "查询当前租户可用的企业数据实体、虚拟数据规模、分页方式和模拟数据标记",
            "parameters": _schema({}),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_enterprise_fab_summary",
            "description": "对当前租户的亿级企业模拟数据执行服务端聚合，返回范围内规模、KPI、设备风险和血缘。结果是确定性投影，不是真实生产观测",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_enterprise_data",
            "description": "从当前租户的企业模拟数据接口抽取最多50条记录用于接口和数据形态分析；结果是样本，不能代表全量统计",
            "parameters": _schema(
                {
                    "entity": {
                        "type": "string",
                        "enum": ["lots", "process-runs", "sensor-events"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                    "product": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["Completed", "Running", "Hold"],
                    },
                    "signal_name": {"type": "string"},
                },
                ["entity"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fab_overview",
            "description": "查询工厂批次、晶圆、良率、周期、hold和异常总览",
            "parameters": _schema(DATE_PROPERTIES),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_yield_trend",
            "description": "按周查询良率和周期趋势，可按产品过滤",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "product": {"type": "string", "description": "产品名，如 Nova-P1"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_pass_rate",
            "description": "查询指定制程的运行通过率（不是最终晶圆良率）；必须按时间和制程过滤，可再限定设备",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                },
                ["process_step"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_equipment_health",
            "description": "查询设备运行数、异常数、缺陷密度、停机和健康状态，可按站点或设备过滤",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_equipment_productivity",
            "description": "按SEMI E10状态查询设备生产、待机、工程和停机时间占比，可按站点或设备过滤",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_capability",
            "description": "按站点关键量测和规格限查询各设备Cpk",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_defect_pareto",
            "description": "查询缺陷类型Pareto和受影响批次数，可按站点过滤",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_excursions",
            "description": "查询最近的制程异常批次及量测值，可按站点或设备过滤",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sensor_summary",
            "description": "按站点、设备或信号查询传感器均值、范围、缺失和异常标记",
            "parameters": _schema(
                {
                    **DATE_PROPERTIES,
                    "process_step": {
                        "type": "string",
                        "enum": list(MANUFACTURING_STEPS),
                    },
                    "equipment_id": {"type": "string"},
                    "signal_name": {"type": "string"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "联合检索当前用户个人知识、厂内SOP、控制计划、分析方法与已验证历史案例。支持中英文制程术语召回，可按元数据过滤，返回可解释评分和reference_id",
            "parameters": _schema(
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    "process_step": {"type": "string", "enum": list(ANALYSIS_SCOPES)},
                    "equipment_id": {"type": "string"},
                    "defect_type": {"type": "string"},
                    "source_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["personal", "knowledge", "case"],
                        },
                    },
                },
                ["query"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_manufacturing_data",
            "description": "在固定报表不足时执行只读SQLite SELECT。只能访问白名单表，最多返回100行",
            "parameters": _schema(
                {
                    "sql": {
                        "type": "string",
                        "description": "单条SELECT语句，SQLite语法",
                    }
                },
                ["sql"],
            ),
        },
    },
    SUBMIT_ANALYSIS_TOOL,
]


__all__ = ["_schema", "DATE_PROPERTIES", "TOOLS"]
