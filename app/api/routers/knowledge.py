from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ...personal_knowledge_runtime.service import PersonalDocumentPatch
from ..schemas import PersonalSearchPreviewRequest
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider, current_personal_user) -> RouterBundle:
    def knowledge_documents() -> list[dict]:
        return deps()["list_knowledge_documents"]()

    def knowledge_document(chunk_id: int) -> dict:
        try:
            return deps()["get_knowledge_document"](chunk_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def upload_personal_knowledge_document(
        background_tasks: BackgroundTasks,
        file: Annotated[UploadFile, File()],
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
        ],
        owner_user_id: Annotated[str, Depends(current_personal_user)],
        metadata: Annotated[str | None, Form()] = None,
    ) -> dict:
        runtime = deps()
        settings = runtime["get_settings"]()
        try:
            data = await file.read(settings.personal_knowledge_max_upload_bytes + 1)
            result = await run_in_threadpool(
                runtime["create_personal_upload"],
                owner_user_id,
                file.filename,
                data,
                metadata,
                idempotency_key,
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc
        finally:
            await file.close()
        if result.pop("_start_processing", False):
            background_tasks.add_task(
                runtime["process_personal_document"],
                result["document_id"],
                owner_user_id,
                result["job_id"],
            )
        return result

    async def personal_knowledge_job_events(
        request: Request,
        owner_user_id: Annotated[str, Depends(current_personal_user)],
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        del last_event_id
        runtime = deps()
        return StreamingResponse(
            runtime["iter_personal_job_events"](
                owner_user_id,
                snapshot_reader=runtime["read_personal_job_snapshots"],
                is_disconnected=request.is_disconnected,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def personal_knowledge_job(
        job_id: str, owner_user_id: Annotated[str, Depends(current_personal_user)]
    ) -> dict:
        runtime = deps()
        try:
            return runtime["get_personal_job"](job_id, owner_user_id)
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def personal_knowledge_documents(
        owner_user_id: Annotated[str, Depends(current_personal_user)],
        q: str = Query("", max_length=100),
        status: str | None = Query(
            None,
            pattern=r"^(uploaded|parsing|chunking|indexing|ready|failed|deleting)$",
        ),
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=500),
    ) -> dict:
        runtime = deps()
        try:
            return runtime["list_personal_documents"](
                owner_user_id, q, status, limit, cursor
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def personal_knowledge_document(
        document_id: str, owner_user_id: Annotated[str, Depends(current_personal_user)]
    ) -> dict:
        runtime = deps()
        try:
            return runtime["get_personal_document"](document_id, owner_user_id)
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def personal_knowledge_document_content(
        document_id: str, owner_user_id: Annotated[str, Depends(current_personal_user)]
    ) -> dict:
        runtime = deps()
        try:
            return runtime["get_personal_document"](
                document_id, owner_user_id, include_chunks=True
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def download_personal_knowledge_document(
        document_id: str, owner_user_id: Annotated[str, Depends(current_personal_user)]
    ):
        runtime = deps()
        try:
            path, filename, mime_type = runtime["personal_document_file"](
                document_id, owner_user_id
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc
        return FileResponse(path, media_type=mime_type, filename=filename)

    def patch_personal_knowledge_document(
        document_id: str,
        request: PersonalDocumentPatch,
        owner_user_id: Annotated[str, Depends(current_personal_user)],
    ) -> dict:
        runtime = deps()
        try:
            return runtime["update_personal_document"](
                document_id, owner_user_id, request
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def retry_personal_knowledge_document(
        document_id: str,
        background_tasks: BackgroundTasks,
        owner_user_id: Annotated[str, Depends(current_personal_user)],
    ) -> dict:
        runtime = deps()
        try:
            result = runtime["retry_personal_document"](document_id, owner_user_id)
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc
        background_tasks.add_task(
            runtime["process_personal_document"],
            document_id,
            owner_user_id,
            result["job_id"],
        )
        return result

    def delete_personal_knowledge_document(
        document_id: str,
        background_tasks: BackgroundTasks,
        owner_user_id: Annotated[str, Depends(current_personal_user)],
    ) -> dict:
        runtime = deps()
        try:
            result = runtime["begin_delete_personal_document"](
                document_id, owner_user_id
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc
        background_tasks.add_task(
            runtime["process_personal_document_deletion"],
            document_id,
            owner_user_id,
            result["job_id"],
        )
        return result

    def personal_knowledge_search_preview(
        request: PersonalSearchPreviewRequest,
        owner_user_id: Annotated[str, Depends(current_personal_user)],
    ) -> dict:
        runtime = deps()
        try:
            results = runtime["search_personal_knowledge"](
                owner_user_id, request.query, request.limit, request.document_ids
            )
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc
        return {"query": request.query, "count": len(results), "results": results}

    def personal_knowledge_chunk(
        chunk_id: str, owner_user_id: Annotated[str, Depends(current_personal_user)]
    ) -> dict:
        runtime = deps()
        try:
            return runtime["get_personal_chunk"](chunk_id, owner_user_id)
        except runtime["PersonalKnowledgeError"] as exc:
            raise runtime["personal_problem"](exc) from exc

    def historical_cases() -> list[dict]:
        return deps()["list_historical_cases"]()

    def historical_case(case_id: str) -> dict:
        try:
            return deps()["get_historical_case"](case_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def rag_search(
        q: str = Query(min_length=2, max_length=500),
        limit: int = Query(6, ge=1, le=10),
        process_step: str | None = None,
        equipment_id: str | None = None,
        defect_type: str | None = None,
        source_type: list[str] | None = Query(None),
    ) -> dict:
        results = deps()["search_knowledge"](
            q, limit, process_step, equipment_id, defect_type, source_type
        )
        return {"query": q, "count": len(results), "results": results}

    router = APIRouter()
    router.add_api_route(
        "/api/knowledge/documents", knowledge_documents, methods=["GET"]
    )
    router.add_api_route(
        "/api/knowledge/chunks/{chunk_id}", knowledge_document, methods=["GET"]
    )
    router.add_api_route(
        "/api/knowledge/personal/documents",
        upload_personal_knowledge_document,
        methods=["POST"],
        status_code=202,
    )
    router.add_api_route(
        "/api/knowledge/personal/jobs/events",
        personal_knowledge_job_events,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge/jobs/{job_id}", personal_knowledge_job, methods=["GET"]
    )
    router.add_api_route(
        "/api/knowledge/personal/documents",
        personal_knowledge_documents,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}",
        personal_knowledge_document,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}/content",
        personal_knowledge_document_content,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}/file",
        download_personal_knowledge_document,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}",
        patch_personal_knowledge_document,
        methods=["PATCH"],
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}/retry",
        retry_personal_knowledge_document,
        methods=["POST"],
        status_code=202,
    )
    router.add_api_route(
        "/api/knowledge/personal/documents/{document_id}",
        delete_personal_knowledge_document,
        methods=["DELETE"],
        status_code=202,
    )
    router.add_api_route(
        "/api/knowledge/personal/search-preview",
        personal_knowledge_search_preview,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/knowledge/personal/chunks/{chunk_id}",
        personal_knowledge_chunk,
        methods=["GET"],
    )
    router.add_api_route("/api/cases", historical_cases, methods=["GET"])
    router.add_api_route("/api/cases/{case_id}", historical_case, methods=["GET"])
    router.add_api_route("/api/rag/search", rag_search, methods=["GET"])
    return RouterBundle(
        router,
        {
            "knowledge_documents": knowledge_documents,
            "knowledge_document": knowledge_document,
            "upload_personal_knowledge_document": upload_personal_knowledge_document,
            "personal_knowledge_job_events": personal_knowledge_job_events,
            "personal_knowledge_job": personal_knowledge_job,
            "personal_knowledge_documents": personal_knowledge_documents,
            "personal_knowledge_document": personal_knowledge_document,
            "personal_knowledge_document_content": personal_knowledge_document_content,
            "download_personal_knowledge_document": download_personal_knowledge_document,
            "patch_personal_knowledge_document": patch_personal_knowledge_document,
            "retry_personal_knowledge_document": retry_personal_knowledge_document,
            "delete_personal_knowledge_document": delete_personal_knowledge_document,
            "personal_knowledge_search_preview": personal_knowledge_search_preview,
            "personal_knowledge_chunk": personal_knowledge_chunk,
            "historical_cases": historical_cases,
            "historical_case": historical_case,
            "rag_search": rag_search,
        },
    )
