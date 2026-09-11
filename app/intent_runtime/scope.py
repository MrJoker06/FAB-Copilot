from __future__ import annotations

import re

from ..manufacturing.processes import MANUFACTURING_STEPS, PROCESS_ALIASES
from .contracts import ManufacturingScopeResolution
from .rules import _FAB_SCOPE_PATTERN, _contains

_SCOPE_NOUN_PATTERN = re.compile(
    r"(?:生产|制造|产线|生产线|机台|设备|制程|站点|运营|运行|良率|缺陷|能力|状况|情况|表现)",
    re.IGNORECASE,
)
_SCOPE_CODE_PATTERN = re.compile(r"(?<![a-z0-9_-])([a-z][a-z0-9_-]{1,31})(?![a-z0-9_-])", re.IGNORECASE)
_SCOPE_CODE_STOPWORDS = {
    "alarm", "cd", "cpk", "defect", "e10", "fab", "hold", "lot", "oee", "pareto",
    "pm", "semi", "sop", "wafer", "wip", "yield",
}
_KNOWN_PRODUCTS = ("Orion-A1", "Orion-A2", "Nova-P1", "Nova-P2", "Atlas-M1")
def _process_steps(normalized: str, equipment_ids: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = {equipment_id.split("-", 1)[0] for equipment_id in equipment_ids}
    for process_step, aliases in PROCESS_ALIASES.items():
        terms = (process_step.lower(), *aliases)
        if any(_contains(normalized, term.lower()) for term in terms):
            found.add(process_step)
    return tuple(step for step in MANUFACTURING_STEPS if step in found)


def _scope_code_mentions(
    normalized: str,
    process_steps: tuple[str, ...],
    equipment_ids: tuple[str, ...],
    products: tuple[str, ...],
) -> tuple[str, ...]:
    known = {
        *(step.lower() for step in process_steps),
        *(equipment_id.lower() for equipment_id in equipment_ids),
        *(product.lower() for product in products),
    }
    mentions: list[str] = []
    for match in _SCOPE_CODE_PATTERN.finditer(normalized):
        token = match.group(1)
        lowered = token.lower()
        if lowered in known or lowered in _SCOPE_CODE_STOPWORDS:
            continue
        context = normalized[max(0, match.start() - 12):min(len(normalized), match.end() + 12)]
        if not _SCOPE_NOUN_PATTERN.search(context):
            continue
        if token not in mentions:
            mentions.append(token.upper())
    return tuple(mentions)


def _manufacturing_scope_resolution(
    question: str,
    normalized: str,
    intent: str,
    process_steps: tuple[str, ...],
    equipment_ids: tuple[str, ...],
) -> ManufacturingScopeResolution:
    manufacturing_intents = {
        "capability_excursion", "yield_decline", "equipment_fault", "lot_trace",
        "defect_analysis", "fab_diagnostic", "fab_overview", "enterprise_data",
    }
    if intent not in manufacturing_intents:
        return ManufacturingScopeResolution("not_applicable", (), (), "deterministic", 1.0, False)
    if equipment_ids:
        return ManufacturingScopeResolution("equipment", equipment_ids, (), "deterministic", 1.0, False)
    if process_steps:
        return ManufacturingScopeResolution("process", process_steps, (), "deterministic", 1.0, False)

    products = tuple(product for product in _KNOWN_PRODUCTS if product.lower() in normalized)
    if products:
        return ManufacturingScopeResolution("product", products, (), "deterministic", 1.0, False)

    unresolved = _scope_code_mentions(normalized, process_steps, equipment_ids, products)
    if unresolved:
        return ManufacturingScopeResolution("unknown", (), unresolved, "deterministic", 0.99, True)
    if _FAB_SCOPE_PATTERN.search(normalized) or intent in {"fab_diagnostic", "fab_overview", "yield_decline"}:
        return ManufacturingScopeResolution("fab", ("FAB",), (), "deterministic", 0.9, False)
    return ManufacturingScopeResolution("not_applicable", (), (), "deterministic", 0.8, False)
