from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal

IntentName = Literal[
    "capability_excursion",
    "yield_decline",
    "equipment_fault",
    "lot_trace",
    "sop_lookup",
    "defect_analysis",
    "fab_diagnostic",
    "fab_overview",
    "enterprise_data",
    "general_knowledge",
    "conversation",
    "ambiguous",
    "unknown",
]
RiskLevel = Literal["low", "medium", "high"]
ScopeType = Literal["fab", "process", "equipment", "product", "unknown", "not_applicable"]
@dataclass(frozen=True)
class RoutedTimeRange:
    start: str
    end: str
    source: Literal["explicit", "relative", "today", "yesterday", "default_90_days"]
    assumed: bool


@dataclass(frozen=True)
class ManufacturingScopeResolution:
    scope_type: ScopeType
    resolved_ids: tuple[str, ...]
    unresolved_mentions: tuple[str, ...]
    source: Literal["deterministic"]
    confidence: float
    clarification_needed: bool


@dataclass(frozen=True)
class IntentRoute:
    intent: IntentName
    intent_label: str
    confidence: float
    candidate_intents: tuple[str, ...]
    process_steps: tuple[str, ...]
    equipment_ids: tuple[str, ...]
    scope_resolution: ManufacturingScopeResolution
    time_range: RoutedTimeRange
    data_requirements: tuple[str, ...]
    risk_level: RiskLevel
    risk_reasons: tuple[str, ...]
    clarification_needed: bool
    clarification_questions: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
