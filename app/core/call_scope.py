"""Result scope implied by one tool call's effective parameters.

The planner declares a step's evidence scope with :func:`call_scope`; the
evidence validator reuses the same function on the executed call's arguments, so
both sides apply one rule set (fab defaults, equipment-before-process, SQL
filters).  It is a pure function over parameters and lives in ``core`` so the
evidence layer can share it without importing orchestration modules.
"""

from __future__ import annotations

import re
from typing import Any


def _scope_values(value: Any) -> tuple[str, ...]:
    """Normalize one scope filter, accepting a scalar or a list of values."""
    raw = value
    if raw in (None, ""):
        return ()
    if not isinstance(raw, (list, tuple, set)):
        raw = (raw,)
    return tuple(sorted({str(item).strip().upper() for item in raw if str(item).strip()}))


def call_scope(
    tool: str, parameters: dict[str, Any], evidence_ids: tuple[str, ...] = ()
) -> dict[str, tuple[str, ...]]:
    """Result scope implied by one tool call's effective parameters."""
    values = {
        "fab_ids": (),
        "process_steps": (),
        "equipment_ids": (),
        "products": (),
        "lot_ids": (),
        "wafer_ids": (),
        "chambers": (),
        "recipes": (),
    }
    if tool in {
        "get_fab_overview",
        "get_process_capability",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_defect_pareto",
        "get_recent_excursions",
        "get_sensor_summary",
        "get_equipment_event_timeline",
        "get_equipment_excursion_history",
    } and not parameters.get("process_step") and not parameters.get("equipment_id"):
        values["fab_ids"] = ("FAB",)
    if tool == "get_yield_trend" and not parameters.get("product"):
        values["fab_ids"] = ("FAB",)
    if tool == "get_product_yield_breakdown" and not parameters.get("product"):
        values["fab_ids"] = ("FAB",)
    # Equipment handlers select equipment first, so do not imply a second
    # process filter merely because the planner also knows the route process.
    equipment = _scope_values(parameters.get("equipment_id") or parameters.get("equipment_ids"))
    process = _scope_values(parameters.get("process_step") or parameters.get("process_steps"))
    if equipment:
        values["equipment_ids"] = equipment
    elif process:
        values["process_steps"] = process
    values["products"] = _scope_values(parameters.get("product") or parameters.get("products"))
    values["lot_ids"] = _scope_values(parameters.get("lot_id") or parameters.get("lot_ids"))
    if tool == "get_equipment_excursion_history" and process:
        values["process_steps"] = process
    if tool == "query_manufacturing_data":
        sql = str(parameters.get("sql", ""))
        lot = re.search(r"\blot_id\s*=\s*'([^']+)'", sql, re.I)
        process_match = re.search(r"\bprocess_step\s*=\s*'([^']+)'", sql, re.I)
        equipment_match = re.search(r"\bequipment_id\s*=\s*'([^']+)'", sql, re.I)
        product = re.search(r"\bproduct\s*=\s*'([^']+)'", sql, re.I)
        if lot:
            values["lot_ids"] = (lot.group(1).upper(),)
        if process_match:
            values["process_steps"] = (process_match.group(1).upper(),)
        if equipment_match:
            values["equipment_ids"] = (equipment_match.group(1).upper(),)
        if product:
            values["products"] = (product.group(1).upper(),)
            values["fab_ids"] = ()
        if not any((lot, process_match, equipment_match, product)):
            tables = {
                name.lower()
                for name in re.findall(r"\bFROM\s+([A-Za-z_][\w.]*)", sql, re.I)
            }
            # Global report templates without a row filter are fab-wide, whether
            # they read lots, equipment events or process runs.  Leaving the
            # scope empty made their facts incompatible with other fab-scoped
            # facts inside one composite inference.
            if tables & {"lots", "equipment_events", "process_runs"}:
                values["fab_ids"] = ("FAB",)
    return values
