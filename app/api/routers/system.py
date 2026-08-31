from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def render_versioned_page(page: Literal["index", "admin"]) -> HTMLResponse:
        runtime = deps()
        html = (
            runtime["_VERSIONED_PAGE_TEMPLATES"][page]
            .read_text(encoding="utf-8")
            .replace("__APP_VERSION__", runtime["APP_VERSION"])
        )
        return HTMLResponse(
            html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )

    async def index():
        return render_versioned_page("index")

    async def admin_index():
        return render_versioned_page("admin")

    def health() -> dict:
        runtime = deps()
        settings = runtime["get_settings"]()
        principal = runtime["current_principal"]()
        model_config = runtime["public_user_model_config"](principal)
        enterprise = runtime["get_enterprise_provider"]().manifest(principal)
        department_names = {"main": "manufacturing"}
        with runtime["db_session"]() as connection:
            lots = connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
            date_range = connection.execute(
                "SELECT MIN(date(start_time)), MAX(date(COALESCE(complete_time, start_time))) FROM lots"
            ).fetchone()
            knowledge_chunks = connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks"
            ).fetchone()[0]
            historical_cases = connection.execute(
                "SELECT COUNT(*) FROM historical_cases"
            ).fetchone()[0]
            process_runs = connection.execute(
                "SELECT COUNT(*) FROM process_runs"
            ).fetchone()[0]
            sensor_readings = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0]
            wafer_maps = connection.execute(
                "SELECT COUNT(*) FROM wafer_maps"
            ).fetchone()[0]
        return {
            "status": "ok",
            "database": {
                "lots": lots,
                "process_runs": process_runs,
                "sensor_readings": sensor_readings,
                "wafer_maps": wafer_maps,
                "start": date_range[0],
                "end": date_range[1],
            },
            "database_departments": {
                department_names.get(name, name): {
                    "path": str(path),
                    "size_bytes": path.stat().st_size if path.exists() else 0,
                }
                for name, path in runtime["department_paths"]().items()
            },
            "model": model_config["provider_model"],
            "model_health": model_config.get("health", {}),
            "agent_configured": model_config["api_key_configured"],
            "build": {
                "version": runtime["APP_VERSION"],
                "git_commit": runtime["GIT_COMMIT"],
            },
            "instance": {
                "id": runtime["os"].getenv("FAB_INSTANCE_ID", "unisolated"),
                "root": runtime["os"].getenv(
                    "FAB_INSTANCE_ROOT", str(runtime["PROJECT_DIR"])
                ),
                "source_root": runtime["os"].getenv(
                    "FAB_SOURCE_ROOT", str(runtime["PROJECT_DIR"])
                ),
            },
            "reference_data": {
                "knowledge_chunks": knowledge_chunks,
                "historical_cases": historical_cases,
            },
            "enterprise": enterprise,
        }

    def version() -> dict:
        runtime = deps()
        return {
            "version": runtime["APP_VERSION"],
            "git_commit": runtime["GIT_COMMIT"],
            "instance_id": runtime["os"].getenv("FAB_INSTANCE_ID", "unisolated"),
        }

    router = APIRouter()
    router.add_api_route("/", index, methods=["GET"], include_in_schema=False)
    router.add_api_route(
        "/admin", admin_index, methods=["GET"], include_in_schema=False
    )
    router.add_api_route("/api/health", health, methods=["GET"])
    router.add_api_route("/api/version", version, methods=["GET"])
    return RouterBundle(
        router,
        {
            "render_versioned_page": render_versioned_page,
            "index": index,
            "admin_index": admin_index,
            "health": health,
            "version": version,
        },
    )
