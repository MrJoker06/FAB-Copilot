"""Small, provider-neutral classification for one model loop response."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .runtime_contracts import ModelResponse, ModelToolCall, RuntimeContractError

_SUBMISSION = "submit_analysis"
_KINDS = frozenset({"text", "submission", "tools", "mixed"})


@dataclass(frozen=True, slots=True)
class LoopResponse:
    kind: Literal["text", "submission", "tools", "mixed"]
    content: str
    tool_calls: tuple[ModelToolCall, ...]

    def __post_init__(self) -> None:
        if self.kind not in _KINDS or not isinstance(self.content, str):
            raise RuntimeContractError("loop response is invalid")
        if not isinstance(self.tool_calls, tuple) or any(
            not isinstance(call, ModelToolCall) for call in self.tool_calls
        ):
            raise RuntimeContractError("loop response is invalid")
        submissions = sum(call.name == _SUBMISSION for call in self.tool_calls)
        if (
            len({call.call_id for call in self.tool_calls}) != len(self.tool_calls)
            or submissions > 1
        ):
            raise RuntimeContractError("loop response is invalid")
        business = len(self.tool_calls) - submissions
        expected = (
            "text"
            if not self.tool_calls
            else "mixed"
            if submissions and business
            else "submission"
            if submissions
            else "tools"
        )
        if self.kind != expected:
            raise RuntimeContractError("loop response is invalid")


def classify_loop_response(value: object) -> LoopResponse:
    """Preserve raw model argument strings while separating synthesis submission."""
    if isinstance(value, ModelResponse):
        content, calls = value.content, value.tool_calls
    elif isinstance(value, dict):
        content = value.get("content", "")
        if content is None:
            content = ""
        raw_calls = value.get("tool_calls", [])
        if raw_calls is None:
            raw_calls = []
        if not isinstance(content, str):
            raise RuntimeContractError("loop response is invalid")
        if not isinstance(raw_calls, list):
            raise RuntimeContractError("loop response is invalid")
        parsed: list[ModelToolCall] = []
        for raw in raw_calls:
            function = raw.get("function") if isinstance(raw, dict) else None
            call_id = raw.get("id") if isinstance(raw, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            arguments = (
                function.get("arguments") if isinstance(function, dict) else None
            )
            try:
                parsed.append(ModelToolCall(call_id, name, arguments))
            except (TypeError, ValueError):
                raise RuntimeContractError("loop response is invalid") from None
        calls = tuple(parsed)
    else:
        raise RuntimeContractError("loop response is invalid")
    submissions = tuple(call for call in calls if call.name == _SUBMISSION)
    business = tuple(call for call in calls if call.name != _SUBMISSION)
    if len({call.call_id for call in calls}) != len(calls) or len(submissions) > 1:
        raise RuntimeContractError("loop response is invalid")
    if not calls:
        kind = "text"
    elif submissions and business:
        kind = "mixed"
    elif submissions:
        kind = "submission"
    else:
        kind = "tools"
    return LoopResponse(kind, content, calls)
