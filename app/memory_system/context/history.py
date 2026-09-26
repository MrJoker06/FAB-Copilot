"""Pure history normalization, selection and message-window helpers."""
from __future__ import annotations

import re

from .protocol import CONTEXTUALIZER_PROMPT


_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.)])\s*(.+?)\s*$")
_MARKDOWN_PATTERN = re.compile(r"[*_`#]+")


def _plain(value: str, limit: int = 1200) -> str:
    return " ".join(_MARKDOWN_PATTERN.sub("", value).strip().split())[:limit]


def _options(content: str) -> list[str]:
    options: list[str] = []
    for line in content.splitlines():
        match = _BULLET_PATTERN.match(line)
        if not match:
            continue
        option = _plain(match.group(1), 500)
        if option:
            options.append(option)
    return options


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        tens, _, ones = value.partition("十")
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return digits.get(value)


def _previous_user_question(history: list[dict], before: int | None = None) -> str:
    boundary = len(history) if before is None else before
    for item in reversed(history[:boundary]):
        if item.get("role") != "user":
            continue
        content = _plain(str(item.get("content") or ""), 1000)
        if content:
            return content
    return ""


def build_contextualizer_messages(
    question: str,
    history: list[dict] | None,
    *,
    message_limit: int = 20,
    character_budget: int = 16_000,
) -> list[dict]:
    candidates: list[dict] = []
    remaining = character_budget
    bounded_history = list(history or [])[-message_limit:]
    indexed_history = [
        {**item, "message_id": int(item.get("message_id") or index + 1)}
        for index, item in enumerate(bounded_history)
    ]
    for item in reversed(indexed_history):
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        prefix = f"[message_id={item['message_id']}] "
        per_message_limit = 1600 if role == "assistant" else 1000
        content = _plain(str(item.get("content") or ""), per_message_limit)
        if not content or remaining <= len(prefix):
            continue
        content = content[:remaining - len(prefix)]
        remaining -= len(prefix) + len(content)
        candidates.append({"role": role, "content": f"{prefix}{content}"})
    candidates.reverse()
    return [
        {"role": "system", "content": CONTEXTUALIZER_PROMPT},
        *candidates,
        {"role": "user", "content": _plain(question, 4000)},
    ]


def _history_index(history: list[dict] | None) -> tuple[list[dict], dict[int, dict]]:
    indexed = [
        {**item, "message_id": int(item.get("message_id") or index + 1)}
        for index, item in enumerate(list(history or []))
    ]
    return indexed, {item["message_id"]: item for item in indexed}


def _recall_records(history: list[dict] | None, target_ids: tuple[int, ...]) -> tuple[dict, ...]:
    indexed, by_id = _history_index(history)
    selected = {message_id for message_id in target_ids if message_id in by_id}
    positions = {item["message_id"]: index for index, item in enumerate(indexed)}
    for message_id in tuple(selected):
        position = positions[message_id]
        item = indexed[position]
        if item.get("role") == "user" and position + 1 < len(indexed):
            following = indexed[position + 1]
            if following.get("role") == "assistant":
                selected.add(following["message_id"])
        elif item.get("role") == "assistant" and position > 0:
            previous = indexed[position - 1]
            if previous.get("role") == "user":
                selected.add(previous["message_id"])
    return tuple(item for item in indexed if item["message_id"] in selected)
