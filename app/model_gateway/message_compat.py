"""Chat-template compatibility shims for OpenAI-compatible model servers.

Fab Insight Agent deliberately appends late system instructions (validator and
synthesizer contracts, loop-guard directives) after history, evidence and tool
messages.  OpenAI-compatible APIs accept that ordering, but Qwen-family chat
templates rendered by llama.cpp ``--jinja`` raise
``Jinja Exception: System message must be at the beginning.`` and the request
fails with HTTP 500.

Flattening every system message into a single leading message keeps the
instruction text and its relative order while satisfying those templates.  The
behaviour is opt-in per deployment through ``FAB_CHAT_TEMPLATE_COMPAT`` so that
providers accepting mid-conversation system messages keep their current
payloads unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

MERGE_SYSTEM_MODE = "merge-system"

_TRUTHY_MODES = frozenset({MERGE_SYSTEM_MODE, "qwen", "1", "true", "on"})


def chat_template_compat_enabled(value: str | None) -> bool:
    """Return whether system-message flattening is requested by configuration."""
    if value is None:
        return False
    return value.strip().lower() in _TRUTHY_MODES


def flatten_system_messages(messages: Sequence[Mapping]) -> list[dict]:
    """Return messages with all system content merged into one leading message.

    Non-system messages keep their original order.  When the conversation is
    already compliant (single system message in the first position) it is
    returned unchanged, so callers can apply this unconditionally.
    """
    system_parts: list[str] = []
    rest: list[Mapping] = []
    system_seen = 0
    for message in messages:
        if not isinstance(message, Mapping):
            rest.append(message)  # type: ignore[arg-type]
            continue
        if message.get("role") == "system":
            system_seen += 1
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue
        rest.append(message)

    if not system_seen:
        return [dict(message) for message in messages]

    if not system_parts:
        return [dict(message) for message in rest]

    if (
        system_seen == 1
        and len(system_parts) == 1
        and isinstance(messages[0], Mapping)
        and messages[0].get("role") == "system"
    ):
        return [dict(message) for message in messages]

    merged = {"role": "system", "content": "\n\n".join(system_parts)}
    return [merged, *(dict(message) for message in rest)]
