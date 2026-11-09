"""Backwards-compatible facade for prompt truncation helpers.

The pure projection implementation lives in ``app.core.tool_result_projection`` so
orchestration stages can use it without importing the evidence layer.  Existing
evidence-layer callers and tests keep this import path.
"""

from __future__ import annotations

from ..core.tool_result_projection import (
    SORTERS,
    TOOL_LIMITS,
    ToolLimit,
    project_result,
    prompt_content,
    truncation_details,
    truncation_notices,
    truncation_prompt_note,
)

__all__ = [
    "SORTERS",
    "TOOL_LIMITS",
    "ToolLimit",
    "project_result",
    "prompt_content",
    "truncation_details",
    "truncation_notices",
    "truncation_prompt_note",
]
