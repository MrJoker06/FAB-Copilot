"""Stable runtime boundaries used by the legacy :mod:`app.agent` facade."""

from .contracts import AgentRunLifecycle, AgentRunRequest, AgentRunResult, ProgressCallback
from .coordinator import CoordinatorDependencies, coordinate_agent_run

__all__ = [
    "AgentRunLifecycle",
    "AgentRunRequest",
    "AgentRunResult",
    "ProgressCallback",
    "CoordinatorDependencies",
    "coordinate_agent_run",
]
