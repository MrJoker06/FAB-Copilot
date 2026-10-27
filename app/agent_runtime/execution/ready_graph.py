"""Stable graph ordering for approved Ready plans."""

from __future__ import annotations

from ...planning_runtime.contracts import ExecutionPlan, PlanStep


def ready_step_order(plan: ExecutionPlan) -> tuple[PlanStep, ...]:
    """Return a stable dependency order and fail closed on an invalid plan graph."""
    if plan.status != "ready":
        return ()
    by_id = {step.step_id: step for step in plan.steps}
    if len(by_id) != len(plan.steps):
        raise ValueError("ready 执行计划包含重复 step_id")
    missing = {
        dependency
        for step in plan.steps
        for dependency in step.depends_on
        if dependency not in by_id
    }
    if missing:
        raise ValueError(f"ready 执行计划引用未知依赖：{', '.join(sorted(missing))}")
    pending = list(plan.steps)
    completed: set[str] = set()
    ordered: list[PlanStep] = []
    while pending:
        ready = next(
            (step for step in pending if set(step.depends_on).issubset(completed)),
            None,
        )
        if ready is None:
            raise ValueError("ready 执行计划包含循环依赖")
        pending.remove(ready)
        ordered.append(ready)
        completed.add(ready.step_id)
    return tuple(ordered)
