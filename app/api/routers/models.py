from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..schemas import ModelConfigRequest
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def get_model_config() -> dict:
        return deps()["public_user_model_config"]()

    def set_model_config(request: ModelConfigRequest) -> dict:
        runtime = deps()
        try:
            result = runtime["select_user_model"](request.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime["emit"](
            "model_config_changed",
            f"config-{uuid.uuid4()}",
            status="success",
            model=result["model"],
            tenant_id=runtime["current_principal"]().tenant_id,
            user_id=runtime["current_principal"]().user_id,
        )
        return result

    router = APIRouter()
    router.add_api_route("/api/settings/model", get_model_config, methods=["GET"])
    router.add_api_route("/api/settings/model", set_model_config, methods=["POST"])
    return RouterBundle(
        router,
        {"get_model_config": get_model_config, "set_model_config": set_model_config},
    )
