"""Fixed import-time inputs for MOD-002 behavior fixture capture.

This module deliberately imports application code only while the context is
active.  Paired workers can therefore load it from their isolated harness
without importing the host application's modules first.
"""

from __future__ import annotations

import importlib
import re
from contextlib import ContextDecorator, ExitStack
from datetime import date
from unittest.mock import patch

CAPTURE_ENVIRONMENT_DATE = date(2026, 10, 22)
FIXTURE_CLOCK = {
    "capture_environment_date": CAPTURE_ENVIRONMENT_DATE.isoformat(),
    "runtime_route_date": "2026-08-07",
    "scope": "input_patch_not_output_normalization",
}
_PROMPT_BANNER = re.compile(r"当前日期是 \d{4}-\d{2}-\d{2}。用户说")


class _CaptureEnvironmentDate(date):
    @classmethod
    def today(cls) -> date:
        return CAPTURE_ENVIRONMENT_DATE


class fixed_capture_clock(ContextDecorator):
    """Temporarily restore the historical host-date inputs used by MOD-002."""

    def __enter__(self):
        service = importlib.import_module("app.agent_runtime.service")
        routing = importlib.import_module("app.intent_runtime.routing")
        prompt = service.SYSTEM_PROMPT
        if not isinstance(prompt, str):
            raise TypeError("MOD-002 SYSTEM_PROMPT must be a string")
        matches = list(_PROMPT_BANNER.finditer(prompt))
        if len(matches) != 1:
            raise RuntimeError(
                "MOD-002 SYSTEM_PROMPT must contain exactly one date banner"
            )
        match = matches[0]
        date_start = match.start() + len("当前日期是 ")
        date_end = date_start + len("YYYY-MM-DD")
        fixed_prompt = (
            prompt[:date_start]
            + CAPTURE_ENVIRONMENT_DATE.isoformat()
            + prompt[date_end:]
        )
        self._stack = ExitStack()
        self._stack.enter_context(patch.object(service, "SYSTEM_PROMPT", fixed_prompt))
        self._stack.enter_context(
            patch.object(routing, "date", _CaptureEnvironmentDate)
        )
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)
