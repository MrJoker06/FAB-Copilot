"""Stable contracts for contextual memory selection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ResolutionStrategy = Literal[
    "none", "ordinal_selection", "semantic_followup", "semantic_correction",
    "semantic_recall", "context_clarification",
]
ContextRelation = Literal["standalone", "followup", "correction", "recall"]
ResolutionSource = Literal["none", "deterministic", "model", "fallback", "circuit_open"]
IntentHint = Literal["conversation", "general_knowledge", "manufacturing_analysis", "unclear"]
ResolutionState = Literal["not_applicable", "resolved", "ambiguous", "unavailable"]


@dataclass(frozen=True)
class ContextResolution:
    original_question: str
    resolved_question: str
    applied: bool
    strategy: ResolutionStrategy
    selected_context: str
    relation: ContextRelation = "standalone"
    confidence: float = 1.0
    source: ResolutionSource = "none"
    intent_hint: IntentHint = "unclear"
    target_message_ids: tuple[int, ...] = ()
    recalled_messages: tuple[dict, ...] = ()
    candidate_messages: tuple[dict, ...] = ()
    failure_reason: str = ""
    resolution_state: ResolutionState = "not_applicable"
    turn_actions: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["target_message_ids"] = list(self.target_message_ids)
        payload["turn_actions"] = [dict(item) for item in self.turn_actions]
        payload.pop("recalled_messages", None)
        payload.pop("candidate_messages", None)
        return payload
