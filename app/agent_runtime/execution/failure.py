"""Side-effect-free predicates used by extracted execution stages.

Health recording and audit ordering remain owned by the calling execution loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFailureDecision:
    """Pure model-availability decision; callers retain side-effect ordering."""

    availability_failure: bool
    retryable: bool
    will_retry: bool
    fallback_before_first_body: bool


def decide_model_failure(
    *, availability_failure: bool, answer_emitted: bool, attempt: int, retry_budget: int
) -> ModelFailureDecision:
    """Compute the legacy retry/fallback fields without recording any side effects."""
    retryable = availability_failure and not answer_emitted
    return ModelFailureDecision(
        availability_failure=availability_failure,
        retryable=retryable,
        will_retry=retryable and attempt <= retry_budget,
        fallback_before_first_body=availability_failure and not answer_emitted,
    )
