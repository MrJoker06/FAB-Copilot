"""Extracted execution stages with lazy compatibility facades."""

# ruff: noqa: RUF022

__all__ = [
    "AgentLoopContext",
    "execute_ready_plan",
    "ready_step_order",
    "run_agent_loop",
    "ModelFailureDecision",
    "decide_model_failure",
]

_EXPORT_MODULES = {
    "AgentLoopContext": ".agent_loop",
    "run_agent_loop": ".agent_loop",
    "execute_ready_plan": ".ready_plan",
    "ready_step_order": ".ready_plan",
    "ModelFailureDecision": ".failure",
    "decide_model_failure": ".failure",
}


def __getattr__(name: str):
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _EXPORT_MODULES[name] == ".agent_loop":
        from . import agent_loop

        value = getattr(agent_loop, name)
    elif _EXPORT_MODULES[name] == ".ready_plan":
        from . import ready_plan

        value = getattr(ready_plan, name)
    else:
        from . import failure

        value = getattr(failure, name)
    globals()[name] = value
    return value
