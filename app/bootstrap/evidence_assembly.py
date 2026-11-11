"""Explicit composition of existing diagnostic evidence with the pure evaluator."""

from __future__ import annotations
from dataclasses import replace
from ..evidence.validator import (
    assess_validation,
    validate_evidence as evaluate_evidence,
)
from ..skills.policies.capability import policy_for


def validate_evidence(
    plan, playbook, observations, *, step_matcher=None, policy_version="2.0.0"
):
    policy = (
        policy_for(playbook, version=policy_version) if playbook is not None else None
    )
    if policy is None and plan.status == "ready" and plan.playbook_id:
        return replace(
            assess_validation(plan, None, []),
            assessment_status="check_failed",
            assessment_reason="required_policy_missing",
            policy_ref={"component_id": plan.playbook_id, "version": policy_version},
            allowed_conclusion_strength="insufficient",
            conclusion_guidance="必需证据策略不可用，不能形成诊断结论。",
        )
    return assess_validation(
        plan,
        policy,
        observations,
        evaluate=lambda: evaluate_evidence(
            plan, policy, observations, step_matcher=step_matcher
        ),
    )
