"""Opt-in evidence matcher for controlled Skill knowledge-focus contracts."""

from __future__ import annotations

from dataclasses import replace

from .validator import (
    EvidenceObservation,
    EvidenceValidation,
    _step_matches,
    validate_evidence,
)


def _same(value: object, expected: object) -> bool:
    if isinstance(value, list):
        return (
            tuple(value) == tuple(expected)
            if isinstance(expected, (list, tuple))
            else False
        )
    return value == expected


def skill_step_matcher(step: object, observation: EvidenceObservation) -> bool:
    """Require native retrieval focus only for the controlled knowledge step."""
    if getattr(step, "tool", None) != "search_knowledge":
        return _step_matches(step, observation)
    parameters = getattr(step, "parameters", {})
    if observation.tool != "search_knowledge" or not isinstance(parameters, dict):
        return False
    for name in ("query", "source_types", "limit"):
        if not _same(observation.arguments.get(name), parameters.get(name)):
            return False
    expected_process = parameters.get("process_step")
    expected_equipment = parameters.get("equipment_id")
    for name, expected in (
        ("process_step", expected_process),
        ("equipment_id", expected_equipment),
    ):
        if name in observation.arguments and observation.arguments[name] != expected:
            return False
    rows = observation.result if isinstance(observation.result, list) else []
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        filters = (
            row.get("retrieval", {}).get("filters", {})
            if isinstance(row.get("retrieval"), dict)
            else {}
        )
        if not isinstance(filters, dict):
            return False
        if (
            expected_process is not None
            and filters.get("process_step") != expected_process
        ):
            return False
        if (
            expected_equipment is not None
            and filters.get("equipment_id") != expected_equipment
        ):
            return False
    return True


def validate_skill_evidence(
    plan: object, playbook: object, observations: list[EvidenceObservation]
) -> EvidenceValidation:
    """Run the canonical validator with only the Skill focus-match extension."""
    return replace(
        validate_evidence(
            plan, playbook, observations, step_matcher=skill_step_matcher
        ),
        validator_version="1.3.0",
    )
