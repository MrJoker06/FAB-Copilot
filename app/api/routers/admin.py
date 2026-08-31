import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..schemas import (
    AdminModelCapabilitiesRequest,
    AdminModelPublishRequest,
    AdminModelStatusRequest,
)
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider, current_admin) -> RouterBundle:
    def _compatibility_failure_report(exc) -> dict:
        return {
            "status": "failed",
            "summary": exc.summary[:500],
            "category": exc.category,
            "retryable": bool(exc.retryable),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }

    def admin_overview(
        _: Annotated[str, Depends(current_admin)],
        hours: int = Query(24, ge=1, le=720),
        recent_limit: int = Query(30, ge=1, le=100),
    ) -> dict:
        runtime = deps()
        overview = runtime["admin_runtime_overview"](hours, recent_limit)
        overview["agent"] = runtime["monitoring_summary"](hours, recent_limit)
        overview["build"] = {
            "version": runtime["APP_VERSION"],
            "git_commit": runtime["GIT_COMMIT"],
        }
        return overview

    def admin_models(_: Annotated[str, Depends(current_admin)]) -> list[dict]:
        return deps()["list_models"](include_retired=True)

    async def admin_publish_model(
        request: AdminModelPublishRequest,
        admin_user: Annotated[str, Depends(current_admin)],
    ) -> dict:
        runtime = deps()
        try:
            model = runtime["publish_model"](
                request.model_id,
                request.display_name,
                request.provider,
                request.provider_model,
                request.base_url,
                request.capabilities.model_dump(),
                admin_user,
            )
        except ValueError as exc:
            message = str(exc)
            raise runtime["http_problem"](
                409 if "已经存在" in message else 400,
                "MODEL_PUBLICATION_FAILED",
                message,
                False,
            ) from exc
        runtime["emit"](
            "model_published",
            f"model-{uuid.uuid4()}",
            status="success",
            model_id=model["model_id"],
            provider=model["provider"],
            provider_model=model["provider_model"],
            created_by=admin_user,
        )
        return model

    def admin_update_model_status(
        model_id: str,
        request: AdminModelStatusRequest,
        admin_user: Annotated[str, Depends(current_admin)],
    ) -> dict:
        runtime = deps()
        try:
            model = runtime["set_model_status"](model_id, request.status)
        except ValueError as exc:
            raise runtime["http_problem"](
                400, "MODEL_STATUS_UPDATE_FAILED", str(exc), False
            ) from exc
        runtime["emit"](
            "model_status_changed",
            f"model-{uuid.uuid4()}",
            status="success",
            model_id=model_id,
            model_status=request.status,
            changed_by=admin_user,
        )
        return model

    def admin_update_model_capabilities(
        model_id: str,
        request: AdminModelCapabilitiesRequest,
        admin_user: Annotated[str, Depends(current_admin)],
    ) -> dict:
        runtime = deps()
        try:
            model = runtime["update_model_capabilities"](model_id, request.model_dump())
        except ValueError as exc:
            raise runtime["http_problem"](
                400, "MODEL_CAPABILITIES_UPDATE_FAILED", str(exc), False
            ) from exc
        runtime["emit"](
            "model_capabilities_updated",
            f"model-{uuid.uuid4()}",
            status="success",
            model_id=model_id,
            changed_by=admin_user,
        )
        return model

    async def admin_check_model_compatibility(
        model_id: str, admin_user: Annotated[str, Depends(current_admin)]
    ) -> dict:
        runtime = deps()
        with runtime["db_session"]() as connection:
            row = connection.execute(
                "SELECT provider, provider_model, base_url, capabilities_json FROM agent.model_catalog WHERE model_id = ?",
                (model_id,),
            ).fetchone()
        if row is None:
            raise runtime["http_problem"](
                404, "MODEL_COMPATIBILITY_FAILED", "模型不存在", False
            )
        try:
            capabilities = json.loads(row["capabilities_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            capabilities = {}
        try:
            configured = runtime["get_settings"]().model_connection
            report = await runtime["check_model_compatibility"](
                runtime["ModelConnection"](
                    row["provider"],
                    configured.api_key,
                    row["base_url"],
                    row["provider_model"],
                ),
                capabilities,
            )
            model = runtime["save_model_compatibility_report"](model_id, report)
        except runtime["ModelCompatibilityError"] as exc:
            failed = runtime["_compatibility_failure_report"](exc)
            runtime["save_model_compatibility_report"](model_id, failed)
            runtime["emit"](
                "model_compatibility_checked",
                f"model-{uuid.uuid4()}",
                status="error",
                model_id=model_id,
                error_category=exc.category,
                retryable=exc.retryable,
                checked_by=admin_user,
            )
            raise runtime["http_problem"](
                422, "MODEL_COMPATIBILITY_FAILED", exc.summary, exc.retryable
            ) from exc
        except ValueError as exc:
            raise runtime["http_problem"](
                400, "MODEL_COMPATIBILITY_FAILED", str(exc), False
            ) from exc
        runtime["emit"](
            "model_compatibility_checked",
            f"model-{uuid.uuid4()}",
            status="success",
            model_id=model_id,
            checks=[item.get("name") for item in report.get("checks", [])],
            duration_ms=report.get("duration_ms"),
            checked_by=admin_user,
        )
        return model

    router = APIRouter()
    router.add_api_route("/api/admin/overview", admin_overview, methods=["GET"])
    router.add_api_route("/api/admin/models", admin_models, methods=["GET"])
    router.add_api_route(
        "/api/admin/models", admin_publish_model, methods=["POST"], status_code=201
    )
    router.add_api_route(
        "/api/admin/models/{model_id}", admin_update_model_status, methods=["PATCH"]
    )
    router.add_api_route(
        "/api/admin/models/{model_id}/capabilities",
        admin_update_model_capabilities,
        methods=["PATCH"],
    )
    router.add_api_route(
        "/api/admin/models/{model_id}/compatibility-check",
        admin_check_model_compatibility,
        methods=["POST"],
    )
    return RouterBundle(
        router,
        {
            "_compatibility_failure_report": _compatibility_failure_report,
            "admin_overview": admin_overview,
            "admin_models": admin_models,
            "admin_publish_model": admin_publish_model,
            "admin_update_model_status": admin_update_model_status,
            "admin_update_model_capabilities": admin_update_model_capabilities,
            "admin_check_model_compatibility": admin_check_model_compatibility,
        },
    )
