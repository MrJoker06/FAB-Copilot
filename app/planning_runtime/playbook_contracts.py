from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal

from ..skills.policies.manufacturing import EvidenceRequirement


PlaybookIntent = Literal[
    "capability_excursion",
    "yield_decline",
    "equipment_fault",
    "lot_trace",
    "sop_lookup",
    "fab_diagnostic",
    "defect_analysis",
]
SelectionStatus = Literal["selected", "clarification_required", "unsupported"]


@dataclass(frozen=True)
class DomainPlaybook:
    playbook_id: str
    schema_version: str
    playbook_version: str
    released_at: str
    intent: PlaybookIntent
    title: str
    objective: str
    required_inputs: tuple[str, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    analysis_questions: tuple[str, ...]
    answer_sections: tuple[str, ...]
    safety_constraints: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlaybookReference:
    playbook_id: str
    playbook_version: str
    intent: str
    title: str


@dataclass(frozen=True)
class PlaybookSelection:
    status: SelectionStatus
    route_intent: str
    selected_playbook: DomainPlaybook | None
    candidate_playbooks: tuple[PlaybookReference, ...]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
