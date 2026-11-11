"""Dashboard composition over the registered fixed report Tool operations."""

from __future__ import annotations

from app.core.report_dates import normalize_range
from app.tools.production_reports.reports import fab_overview
from app.tools.production_reports.reports import yield_trend
from app.tools.equipment_health.reports import equipment_health
from app.tools.operational_reports.reports import defect_pareto
from app.tools.operational_reports.reports import recent_excursions


def report_bundle(start: str | None = None, end: str | None = None) -> dict:
    start, end = normalize_range(start, end)
    return {
        "overview": fab_overview(start, end),
        "yield_trend": yield_trend(start, end),
        "equipment": equipment_health(start, end),
        "defects": defect_pareto(start, end, 8),
        "excursions": recent_excursions(start, end, 12),
    }
