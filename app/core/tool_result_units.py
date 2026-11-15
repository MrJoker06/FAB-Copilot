"""Lossless logical units for stored results; no storage or runtime imports."""

from __future__ import annotations

import json
import math
import re


def canonical_json(value: object) -> str:
    def validate(item: object) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child)
            return
        raise ValueError("Result must contain finite JSON values")

    validate(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def result_units(value: object) -> tuple[str, list]:
    canonical_json(value)
    if type(value) is list:
        return "records", value
    if type(value) is str:
        return "paragraphs", [
            part for part in re.findall(r".*?(?:\n[ \t]*\n|\Z)", value, re.S) if part
        ]
    if type(value) is dict:
        return "entries", [{"key": key, "value": item} for key, item in value.items()]
    return "scalar", [value]


def result_page(
    value: object,
    metadata: dict,
    *,
    index: int,
    char_offset: int,
    limit: int,
    max_bytes: int,
    cursor_for,
) -> dict:
    """Return full units first; fragment only a unit that cannot fit alone.

    All sizes include the complete JSON response, signed cursor and metadata.
    A fragment's text is a slice of the canonical JSON of one logical unit.
    """
    kind, units = result_units(value)
    if (
        type(index) is not int
        or type(char_offset) is not int
        or min(index, char_offset) < 0
    ):
        raise ValueError("Invalid cursor")
    if index > len(units) or (index == len(units) and char_offset):
        raise ValueError("Invalid cursor")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Invalid page limit")

    def build(payload: dict, next_index: int, next_char: int = 0) -> dict:
        more = next_index < len(units)
        return {
            **metadata,
            "unit_kind": kind,
            "total_units": len(units),
            **payload,
            "next_cursor": cursor_for(next_index, next_char) if more else None,
            "has_more": more,
        }

    def fits(page: dict) -> bool:
        return len(canonical_json(page).encode("utf-8")) <= max_bytes

    page = build({"format": "units", "start_unit": index, "units": []}, index)
    if char_offset == 0:
        for end in range(index + 1, min(index + limit, len(units)) + 1):
            candidate = build(
                {"format": "units", "start_unit": index, "units": units[index:end]}, end
            )
            if not fits(candidate):
                break
            page = candidate
        if page["units"] or index == len(units):
            if not fits(page):
                raise ValueError("Result response budget exhausted")
            return page

    text = canonical_json(units[index])
    if char_offset >= len(text):
        raise ValueError("Invalid cursor")
    low, high = 1, min(2048, len(text) - char_offset)
    best = None
    while low <= high:
        length = (low + high) // 2
        end = char_offset + length
        candidate = build(
            {
                "format": "unit_fragment",
                "unit_index": index,
                "start_char": char_offset,
                "end_char": end,
                "total_chars": len(text),
                "text": text[char_offset:end],
            },
            index + 1 if end == len(text) else index,
            0 if end == len(text) else end,
        )
        if fits(candidate):
            best, low = candidate, length + 1
        else:
            high = length - 1
    if best is None:
        raise ValueError("Result response budget exhausted")
    return best
