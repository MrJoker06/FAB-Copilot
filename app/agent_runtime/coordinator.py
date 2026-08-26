"""Compatibility coordinator for the legacy Agent implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .contracts import AgentRunRequest, AgentRunResult, ProgressCallback


LegacyAgentImplementation = Callable[
    [str, list[dict] | None, str, ProgressCallback | None, bool], Awaitable[AgentRunResult]
]


async def coordinate_agent_run(
    request: AgentRunRequest,
    progress: ProgressCallback | None,
    *,
    implementation: LegacyAgentImplementation,
) -> AgentRunResult:
    """Forward exactly to the legacy implementation while stages are migrated."""

    return await implementation(
        request.question,
        request.history,
        request.run_id,
        progress,
        request.thinking,
    )
