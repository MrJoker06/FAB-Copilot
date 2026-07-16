from __future__ import annotations

from datetime import date

import pytest
from fab_contracts import DateRange, IdentityContext, ReportRequest
from pydantic import ValidationError


def test_contracts_normalize_process_and_reject_invalid_ranges() -> None:
    request = ReportRequest(process_step="cvd", limit=10)
    assert request.process_step == "CVD"
    identity = IdentityContext(user_id="analyst", request_id="req-12345678", scopes=("analytics:adhoc",))
    assert identity.has_scope("analytics:adhoc")
    with pytest.raises(ValidationError):
        DateRange(start=date(2026, 7, 10), end=date(2026, 7, 1))
