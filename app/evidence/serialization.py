"""Equivalent, allocation-conscious JSON payloads for evidence dataclasses."""

from __future__ import annotations

import copy
import json
from dataclasses import fields, is_dataclass
from typing import Any

_EXACT_IMMUTABLE_TYPES = frozenset({type(None), bool, int, float, str})


def _asdict_inner(value: Any) -> Any:
    if type(value) in _EXACT_IMMUTABLE_TYPES:
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _asdict_inner(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return type(value)(*(_asdict_inner(item) for item in value))
    if isinstance(value, (list, tuple)):
        return type(value)(_asdict_inner(item) for item in value)
    if isinstance(value, dict):
        return type(value)(
            (_asdict_inner(key), _asdict_inner(item)) for key, item in value.items()
        )
    return copy.deepcopy(value)


def json_dataclass_payload(value: Any) -> dict[str, Any]:
    """Return the existing ``asdict`` plus JSON round-trip payload semantics."""
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("asdict() should be called on dataclass instances")
    return json.loads(json.dumps(_asdict_inner(value), ensure_ascii=False, default=str))
