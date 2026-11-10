"""Public model capability contract shared by the model registry and storage migration."""

from __future__ import annotations

MODEL_CAPABILITY_DEFAULTS = {
    "streaming": True,
    "tool_calls": True,
    "thinking": False,
    "native_multimodal": False,
}

THINKING_EFFORTS = ("off", "low", "medium", "high", "xhigh")
THINKING_DIALECTS = ("qwen", "deepseek", "openai")
THINKING_DEFAULT_OPTIONS = {
    "qwen": ("low", "medium", "xhigh"),
    "deepseek": ("low", "medium", "high"),
    "openai": ("low", "medium", "high"),
}
THINKING_DEFAULT_EFFORT = {
    "qwen": "xhigh",
    "deepseek": "high",
    "openai": "high",
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


def infer_thinking_dialect(
    capabilities: dict | None, provider: str = "", provider_model: str = ""
) -> str:
    """Resolve the provider wire dialect used for per-request reasoning controls."""
    source = capabilities if isinstance(capabilities, dict) else {}
    declared = source.get("reasoning_dialect")
    if declared in THINKING_DIALECTS:
        return str(declared)
    if provider == "deepseek":
        return "deepseek"
    if "qwen" in str(provider_model).lower():
        return "qwen"
    return "openai"


def thinking_settings(
    capabilities: object | None,
    *,
    provider: str = "",
    provider_model: str = "",
) -> dict:
    """Return the public default effort and the subset users may choose.

    ``off`` is always available to the client and is not repeated in
    ``options``.  A model that does not declare thinking is forced off.
    """
    source = normalize_capabilities(capabilities)
    dialect = infer_thinking_dialect(source, provider, provider_model)
    if not source.get("thinking", False):
        return {
            "thinking": False,
            "effort": "off",
            "options": [],
            "dialect": dialect,
        }
    declared_options = source.get("thinking_effort_options")
    candidates = (
        [item for item in declared_options if item in THINKING_EFFORTS[1:]]
        if isinstance(declared_options, list)
        else []
    )
    options: list[str] = []
    for item in candidates:
        if item not in options:
            options.append(item)
    if not options:
        options = list(THINKING_DEFAULT_OPTIONS[dialect])
    default = source.get("thinking_effort")
    if default not in options and default != "off":
        default = (
            THINKING_DEFAULT_EFFORT[dialect]
            if THINKING_DEFAULT_EFFORT[dialect] in options
            else options[-1]
        )
    return {
        "thinking": True,
        "effort": default,
        "options": options,
        "dialect": dialect,
    }


def normalize_capability_declaration(
    capabilities: dict, *, provider: str = "", provider_model: str = ""
) -> dict:
    """Validate an administrator declaration and keep the optional thinking keys."""
    if not isinstance(capabilities, dict):
        raise ValueError("能力配置格式不正确")
    source = normalize_capabilities(capabilities)
    extras = {
        key: capabilities[key]
        for key in (
            "thinking_effort",
            "thinking_effort_options",
            "reasoning_dialect",
        )
        if key in capabilities
    }
    if "thinking_effort" in extras and extras["thinking_effort"] not in THINKING_EFFORTS:
        raise ValueError("思考档位不正确")
    if "thinking_effort_options" in extras:
        options = extras["thinking_effort_options"]
        if not isinstance(options, list) or not all(
            item in THINKING_EFFORTS[1:] for item in options
        ):
            raise ValueError("可选思考档位不正确")
        extras["thinking_effort_options"] = list(dict.fromkeys(options))
    if "reasoning_dialect" in extras and extras["reasoning_dialect"] not in THINKING_DIALECTS:
        raise ValueError("推理方言不正确")
    declaration = {key: source[key] for key in MODEL_CAPABILITY_DEFAULTS}
    declaration.update(extras)
    if not declaration["thinking"]:
        declaration["thinking_effort"] = "off"
        declaration["thinking_effort_options"] = []
    else:
        declared_effort = extras.get("thinking_effort")
        declared_options = extras.get("thinking_effort_options")
        if declared_options is not None and not declared_options:
            raise ValueError("至少选择一个思考档位")
        if (
            declared_effort not in (None, "off")
            and declared_options is not None
            and declared_effort not in declared_options
        ):
            raise ValueError("默认思考档位不在可选档位中")
        settings = thinking_settings(
            declaration, provider=provider, provider_model=provider_model
        )
        declaration["thinking_effort"] = settings["effort"]
        declaration["thinking_effort_options"] = settings["options"]
        declaration["reasoning_dialect"] = settings["dialect"]
    return declaration


__all__ = [
    "MODEL_CAPABILITY_DEFAULTS",
    "THINKING_DIALECTS",
    "THINKING_DEFAULT_EFFORT",
    "THINKING_DEFAULT_OPTIONS",
    "THINKING_EFFORTS",
    "infer_thinking_dialect",
    "normalize_capabilities",
    "normalize_capability_declaration",
    "thinking_settings",
]
