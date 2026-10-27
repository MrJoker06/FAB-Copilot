"""Deterministic planning implementation boundary."""

__all__ = [
    "ExecutionPlan",
    "PlanBudget",
    "PlanStep",
    "create_execution_plan",
    "planner_system_message",
]

_EXPORT_MODULES = {
    "ExecutionPlan": ".contracts",
    "PlanBudget": ".contracts",
    "PlanStep": ".contracts",
    "create_execution_plan": ".service",
    "planner_system_message": ".service",
}


def __getattr__(name: str):
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _EXPORT_MODULES[name] == ".contracts":
        from . import contracts

        value = getattr(contracts, name)
    else:
        from . import service

        value = getattr(service, name)
    globals()[name] = value
    return value
