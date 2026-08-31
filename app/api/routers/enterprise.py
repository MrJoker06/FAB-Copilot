from __future__ import annotations

from fastapi import APIRouter, Query

from ...processes import PROCESS_STEP_PATTERN
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def enterprise_context() -> dict:
        runtime = deps()
        settings = runtime["get_settings"]()
        principal = runtime["current_principal"]()
        return {
            "mode": "enterprise" if settings.enterprise_mode else "personal",
            "identity": principal.public_dict(),
            "knowledge_owner_scope": principal.knowledge_owner_id,
            "data": runtime["get_enterprise_provider"]().manifest(principal),
        }

    def _enterprise_page(
        entity: str, limit: int, cursor: str | None, filters: dict
    ) -> dict:
        runtime = deps()
        try:
            query_filters = {
                key: value
                for key, value in filters.items()
                if key not in {"entity", "limit", "cursor"}
            }
            return runtime["get_enterprise_provider"]().page(
                entity, runtime["current_principal"](), limit, cursor, query_filters
            )
        except runtime["EnterpriseDataError"] as exc:
            raise runtime["http_problem"](
                400, exc.error_code, exc.detail, False
            ) from exc

    def enterprise_manifest() -> dict:
        return deps()["get_enterprise_provider"]().manifest(
            deps()["current_principal"]()
        )

    def enterprise_summary(
        start: str | None = None,
        end: str | None = None,
        process_step: str | None = Query(None, pattern=PROCESS_STEP_PATTERN),
        equipment_id: str | None = Query(None, min_length=2, max_length=64),
    ) -> dict:
        runtime = deps()
        try:
            return runtime["get_enterprise_provider"]().summary(
                runtime["current_principal"](),
                {
                    "start": start,
                    "end": end,
                    "process_step": process_step,
                    "equipment_id": equipment_id,
                },
            )
        except runtime["EnterpriseDataError"] as exc:
            raise runtime["http_problem"](
                400, exc.error_code, exc.detail, False
            ) from exc

    def enterprise_lots(
        limit: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
        start: str | None = None,
        end: str | None = None,
        product: str | None = None,
        status: str | None = None,
    ) -> dict:
        return _enterprise_page(
            "lots",
            limit,
            cursor,
            {"start": start, "end": end, "product": product, "status": status},
        )

    def enterprise_process_runs(
        limit: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
        start: str | None = None,
        end: str | None = None,
        process_step: str | None = None,
        equipment_id: str | None = None,
    ) -> dict:
        return _enterprise_page(
            "process-runs",
            limit,
            cursor,
            {
                "start": start,
                "end": end,
                "process_step": process_step,
                "equipment_id": equipment_id,
            },
        )

    def enterprise_sensor_events(
        limit: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
        start: str | None = None,
        end: str | None = None,
        process_step: str | None = None,
        equipment_id: str | None = None,
        signal_name: str | None = None,
    ) -> dict:
        return _enterprise_page(
            "sensor-events",
            limit,
            cursor,
            {
                "start": start,
                "end": end,
                "process_step": process_step,
                "equipment_id": equipment_id,
                "signal_name": signal_name,
            },
        )

    router = APIRouter()
    for path, endpoint in [
        ("/api/enterprise/context", enterprise_context),
        ("/api/enterprise/data/manifest", enterprise_manifest),
        ("/api/enterprise/data/summary", enterprise_summary),
        ("/api/enterprise/data/lots", enterprise_lots),
        ("/api/enterprise/data/process-runs", enterprise_process_runs),
        ("/api/enterprise/data/sensor-events", enterprise_sensor_events),
    ]:
        router.add_api_route(path, endpoint, methods=["GET"])
    return RouterBundle(
        router,
        {
            "enterprise_context": enterprise_context,
            "_enterprise_page": _enterprise_page,
            "enterprise_manifest": enterprise_manifest,
            "enterprise_summary": enterprise_summary,
            "enterprise_lots": enterprise_lots,
            "enterprise_process_runs": enterprise_process_runs,
            "enterprise_sensor_events": enterprise_sensor_events,
        },
    )
