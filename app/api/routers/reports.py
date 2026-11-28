from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.manufacturing_terms import PROCESS_STEP_PATTERN
from app.demo_data import shift_checklist
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def dashboard(start: str | None = None, end: str | None = None) -> dict:
        try:
            return deps()["report_bundle"](start, end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def capability(
        process_step: str = Query("CVD", pattern=PROCESS_STEP_PATTERN),
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        try:
            return deps()["process_capability"](start, end, process_step)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def duty_checklist(
        role: Literal["PE", "EE"] | None = None,
        work_date: date | None = None,
        shift: Literal["day", "night"] = "day",
    ) -> dict:
        principal = deps()["current_principal"]()
        roles = shift_checklist.allowed_roles(principal)
        if not roles:
            raise deps()["http_problem"](403, "CAPABILITY_DENIED", "当前身份无权查看开班检查", False)
        try:
            result = shift_checklist.checklist(
                principal, role or roles[0], work_date or datetime.now(shift_checklist.SHIFT_TZ).date(), shift,
            )
        except shift_checklist.ChecklistError as exc:
            raise deps()["http_problem"](exc.status, exc.code, str(exc), False) from None
        return {**result, "available_roles": roles}

    router = APIRouter()
    router.add_api_route("/api/reports/duty-checklist", duty_checklist, methods=["GET"])
    router.add_api_route("/api/reports/dashboard", dashboard, methods=["GET"])
    router.add_api_route("/api/reports/capability", capability, methods=["GET"])
    return RouterBundle(router, {"dashboard": dashboard, "capability": capability})
