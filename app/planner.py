"""Compatibility facade for deterministic planning."""

from typing import Any

from .planning_runtime import contracts as _contracts
from .planning_runtime import queries as _queries
from .planning_runtime import scope as _scope
from .planning_runtime import service as _service
from .planning_runtime import steps as _steps
from .planning_runtime.contracts import *  # noqa: F403
from .planning_runtime.queries import *  # noqa: F403
from .planning_runtime.scope import *  # noqa: F403
from .planning_runtime.service import *  # noqa: F403
from .planning_runtime.steps import *  # noqa: F403

_analysis_scope_contract = _scope._analysis_scope_contract
_manufacturing_queries = _queries._manufacturing_queries
_ready_steps = _steps._ready_steps


def __getattr__(name: str) -> Any:
    for module in (_contracts, _queries, _scope, _steps, _service):
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(name)
