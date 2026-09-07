"""Explicit coordinator stages; legacy coordinator_* modules are compatibility shims."""

from .availability import AvailabilityOutcome, handle_model_availability
from .loop import execute_agent_loop
from .model import build_result, prepare_model_stage
from .prepare import PrepareImmediateOutcome, prepare_immediate
from .ready import execute_ready_synthesis

__all__ = [
    "AvailabilityOutcome", "PrepareImmediateOutcome", "build_result", "execute_agent_loop",
    "execute_ready_synthesis", "handle_model_availability", "prepare_immediate", "prepare_model_stage",
]
