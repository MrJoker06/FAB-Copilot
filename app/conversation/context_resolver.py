"""Compatibility facade for the extracted contextual-memory implementation.

The canonical owner is :mod:`app.memory_system`. Keep these explicit exports
while existing integrations and patch paths still import the conversation path.
"""
from __future__ import annotations

from ..memory_system.contracts import (
    ContextRelation,
    ContextResolution,
    IntentHint,
    ResolutionSource,
    ResolutionState,
    ResolutionStrategy,
)
from ..memory_system.context.builder import context_system_message
from ..memory_system.context.history import (
    _BULLET_PATTERN,
    _MARKDOWN_PATTERN,
    _history_index,
    _number,
    _options,
    _plain,
    _previous_user_question,
    _recall_records,
    build_contextualizer_messages,
)
from ..memory_system.context.protocol import (
    CONTEXTUALIZER_PROMPT,
    CONTEXTUALIZER_RESPONSE_FORMAT,
    ContextPayloadValidationError,
    validate_contextualizer_payload,
)
from ..memory_system.context.resolver import (
    _LAST_PATTERN,
    _ORDINAL_PATTERN,
    _resolve_ordinal,
    context_clarification_resolution,
    resolve_question_context,
    semantic_context_resolution,
    unresolved_context,
)

__all__ = (
    "CONTEXTUALIZER_PROMPT", "CONTEXTUALIZER_RESPONSE_FORMAT",
    "ContextPayloadValidationError", "ContextRelation", "ContextResolution",
    "IntentHint", "ResolutionSource", "ResolutionState", "ResolutionStrategy",
    "_BULLET_PATTERN", "_LAST_PATTERN", "_MARKDOWN_PATTERN", "_ORDINAL_PATTERN",
    "_history_index", "_number", "_options", "_plain", "_previous_user_question",
    "_recall_records", "_resolve_ordinal", "build_contextualizer_messages",
    "context_clarification_resolution", "context_system_message",
    "resolve_question_context", "semantic_context_resolution", "unresolved_context",
    "validate_contextualizer_payload",
)
