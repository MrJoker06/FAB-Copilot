"""Answer synthesis stages with compatibility dependencies supplied by ``app.agent_runtime.service``."""

from .fallback import OfflineAnswerDependencies, offline_answer
from .ready import (
    ReadySynthesisDependencies,
    ready_synthesis_fallback,
    ready_synthesis_messages,
    request_synthesis_correction,
    request_ready_synthesis,
    synthesize_ready_assistant,
)
from .result import build_ready_model_unavailable_result, build_result

__all__ = [
    "OfflineAnswerDependencies",
    "ReadySynthesisDependencies",
    "build_result",
    "build_ready_model_unavailable_result",
    "offline_answer",
    "ready_synthesis_fallback",
    "ready_synthesis_messages",
    "request_ready_synthesis",
    "request_synthesis_correction",
    "synthesize_ready_assistant",
]
