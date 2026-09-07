"""Stable runtime boundaries used by the legacy :mod:`app.agent` facade."""

from .contracts import AgentRunLifecycle, AgentRunRequest, AgentRunResult, ProgressCallback
from .coordinator import coordinate_agent_run
from .dependencies import CoordinatorDependencies

__all__ = [
    "AgentRunLifecycle",
    "AgentRunRequest",
    "AgentRunResult",
    "ProgressCallback",
    "CoordinatorDependencies",
    "coordinate_agent_run",
]
