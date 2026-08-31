from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..schemas import StreamTelemetryRequest
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider, current_admin) -> RouterBundle:
    def record_stream_telemetry(request: StreamTelemetryRequest) -> dict:
        deps()["emit"](
            "browser_stream_summary",
            request.run_id,
            **request.model_dump(exclude={"run_id"}),
        )
        return {"accepted": True}

    def monitor_summary(
        _: Annotated[str, Depends(current_admin)],
        hours: int = Query(24, ge=1, le=720),
        recent_limit: int = Query(20, ge=1, le=100),
    ) -> dict:
        return deps()["monitoring_summary"](hours, recent_limit)

    def monitor_events(
        _: Annotated[str, Depends(current_admin)],
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict]:
        return list(reversed(deps()["read_events"](limit)))

    router = APIRouter()
    router.add_api_route(
        "/api/telemetry/stream", record_stream_telemetry, methods=["POST"]
    )
    router.add_api_route("/api/monitor/summary", monitor_summary, methods=["GET"])
    router.add_api_route("/api/monitor/events", monitor_events, methods=["GET"])
    return RouterBundle(
        router,
        {
            "record_stream_telemetry": record_stream_telemetry,
            "monitor_summary": monitor_summary,
            "monitor_events": monitor_events,
        },
    )
