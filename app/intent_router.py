"""Compatibility facade for deterministic intent routing."""

from typing import Any

from .intent_runtime import contracts as _contracts
from .intent_runtime import routing as _routing
from .intent_runtime import rules as _rules
from .intent_runtime import scope as _scope
from .intent_runtime import time as _time
from .intent_runtime.contracts import *  # noqa: F403
from .intent_runtime.rules import *  # noqa: F403
from .intent_runtime.scope import *  # noqa: F403
from .intent_runtime.time import *  # noqa: F403
from .intent_runtime.routing import *  # noqa: F403


def __getattr__(name: str) -> Any:
    for module in (_contracts, _rules, _scope, _time, _routing):
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(name)
