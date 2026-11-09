"""Public model capability contract shared by the model registry and storage migration."""

from __future__ import annotations

MODEL_CAPABILITY_DEFAULTS = {
    "streaming": True,
    "tool_calls": True,
    "thinking": False,
    "native_multimodal": False,
}


def normalize_capabilities(value: object | None) -> dict:
    """Preserve extension keys while providing the complete public contract."""
    source = value if isinstance(value, dict) else {}
    normalized = dict(source)
    for key, default in MODEL_CAPABILITY_DEFAULTS.items():
        normalized[key] = (
            source.get(key) if isinstance(source.get(key), bool) else default
        )
    return normalized


__all__ = ["MODEL_CAPABILITY_DEFAULTS", "normalize_capabilities"]
