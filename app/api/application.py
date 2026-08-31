from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncContextManager, Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


@dataclass(frozen=True)
class ApplicationDependencies:
    ensure_department_databases: Callable[[], None]
    recover_interrupted_executions: Callable[[], None]
    ensure_model_catalog: Callable[[], None]
    db_session: Callable
    manufacturing_steps: tuple | list
    generate_database: Callable[[], None]
    seed_reference_data: Callable[[], None]
    pending_personal_jobs: Callable[[], object]
    process_personal_document: Callable
    process_personal_document_deletion: Callable
    to_thread: Callable = asyncio.to_thread


def lifespan_for(deps: ApplicationDependencies):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        deps.ensure_department_databases()
        deps.recover_interrupted_executions()
        deps.ensure_model_catalog()
        with deps.db_session() as connection:
            populated_steps = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT process_step FROM process_runs WHERE measurement_value IS NOT NULL"
                )
            }
            has_sensor_data = bool(
                connection.execute("SELECT EXISTS(SELECT 1 FROM sensor_readings LIMIT 1)").fetchone()[0]
            )
            max_operation = connection.execute("SELECT MAX(operation_seq) FROM process_runs").fetchone()[0] or 0
            knowledge_count = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        if not set(deps.manufacturing_steps).issubset(populated_steps) or not has_sensor_data or max_operation < 18:
            deps.generate_database()
        elif knowledge_count == 0:
            deps.seed_reference_data()
        for document_id, owner_user_id, job_id, status in deps.pending_personal_jobs():
            worker = deps.process_personal_document_deletion if status == "deleting" else deps.process_personal_document
            await deps.to_thread(worker, document_id, owner_user_id, job_id)
        yield
    return lifespan


def create_application(
    *,
    lifespan: Callable[[FastAPI], AsyncContextManager[None]],
    project_dir: Path,
    principal_context_middleware,
    request_audit_middleware,
) -> FastAPI:
    app = FastAPI(
        title="Fab Insight Agent",
        version="1.0.0",
        description="虚拟半导体制造报表、RAG 与数据分析 Agent",
        lifespan=lifespan,
    )
    app.add_middleware(principal_context_middleware)
    app.add_middleware(request_audit_middleware)
    app.mount("/static", StaticFiles(directory=project_dir / "app" / "static"), name="static")
    return app
