from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...manufacturing.processes import PROCESS_STEP_PATTERN
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

    router = APIRouter()
    router.add_api_route("/api/reports/dashboard", dashboard, methods=["GET"])
    router.add_api_route("/api/reports/capability", capability, methods=["GET"])
    return RouterBundle(router, {"dashboard": dashboard, "capability": capability})
