import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from ...core.manufacturing_terms import MANUFACTURING_STEPS
from ...core.settings import PROJECT_DIR
from ...knowledge import shared_documents as store
from ...personal_knowledge_runtime.contracts import PersonalKnowledgeError
from ..schemas import FolderAccess, ModuleId, ModulePreview
from .runtime import NamespaceProvider, RouterBundle


class SharedDocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["sop", "case"]
    process: str = Field(default="", max_length=20)
    enabled: bool
    area: ModuleId | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("标题不能为空")
        return value

    @field_validator("process")
    @classmethod
    def clean_process(cls, value):
        if value and value not in MANUFACTURING_STEPS:
            raise ValueError("不支持的制程")
        return value


def shared_documents_root() -> Path:
    configured = os.getenv("FAB_SHARED_DOCUMENTS_ROOT", "").strip()
    path = Path(configured) if configured else PROJECT_DIR / "runtime/local/shared_documents"
    return path if path.is_absolute() else PROJECT_DIR / path


def resume_shared_documents():
    store.resume_pending(storage_root=shared_documents_root())


def create_router(deps: NamespaceProvider, current_personal_user, current_admin):
    router = APIRouter()

    def invoke(operation, *args, **kwargs):
        try:
            return operation(*args, storage_root=shared_documents_root(), **kwargs)
        except PersonalKnowledgeError as exc:
            raise deps()["personal_problem"](exc) from exc
        except (OSError, sqlite3.Error):
            raise deps()["http_problem"](503, "SHARED_DOCUMENTS_UNAVAILABLE", "共享资料服务暂不可用", True) from None

    @router.get("/api/knowledge/shared/documents")
    def documents(_: Annotated[str, Depends(current_personal_user)]):
        principal = deps()["current_principal"]()
        return {"items": invoke(store.list_documents, principal),
                "areas": invoke(store.list_areas, modules=principal.modules)}

    def upload_handler(identity, *, admin=False):
        async def upload(background_tasks: BackgroundTasks,
            file: Annotated[UploadFile, File()],
            _: Annotated[str, Depends(identity)],
            kind: Annotated[Literal["sop", "case"], Form()],
            area: Annotated[ModuleId | None, Form()] = None,
            title: Annotated[str, Form(max_length=200)] = "",
            process: Annotated[str, Form(max_length=20)] = ""):
            try:
                try:
                    metadata = SharedDocumentPatch(title=title.strip() or (file.filename or "资料"),kind=kind,process=process,enabled=True)
                except ValidationError:
                    raise deps()["http_problem"](422, "INVALID_DOCUMENT_METADATA", "请检查标题与制程信息", False) from None
                limit = deps()["get_settings"]().personal_knowledge_max_upload_bytes
                data = await file.read(limit + 1)
                if len(data) > limit:
                    raise deps()["http_problem"](413, "FILE_TOO_LARGE", "文件超过上传大小限制", False)
                principal = deps()["current_principal"]()
                document_id = await run_in_threadpool(invoke, store.create_upload, principal, file.filename, data, metadata.kind, metadata.title, metadata.process, area=area, admin=admin)
            finally:
                await file.close()
            background_tasks.add_task(store.process_document, document_id, storage_root=shared_documents_root())
            return {"document_id": document_id, "status": "processing"}
        return upload

    router.add_api_route("/api/knowledge/shared/documents", upload_handler(current_personal_user),
                         methods=["POST"], status_code=202)
    router.add_api_route("/api/admin/shared-documents", upload_handler(current_admin, admin=True),
                         methods=["POST"], status_code=202, name="admin_upload_document")

    @router.get("/api/knowledge/shared/documents/{document_id}")
    def document(document_id: str, _: Annotated[str, Depends(current_personal_user)]):
        return invoke(store.get_document, document_id, deps()["current_principal"]())[0]

    @router.get("/api/knowledge/shared/documents/{document_id}/file")
    def download(document_id: str, _: Annotated[str, Depends(current_personal_user)]):
        path, filename, mime = invoke(store.document_file, document_id, deps()["current_principal"]())
        return FileResponse(path,filename=filename,media_type=mime,headers={"X-Content-Type-Options":"nosniff"})

    @router.get("/api/admin/shared-documents")
    def admin_documents(_: Annotated[str, Depends(current_admin)]):
        return {"items": invoke(store.list_documents, admin=True), "areas": invoke(store.list_areas, admin=True)}

    @router.put("/api/admin/shared-document-areas")
    def configure_area(request: FolderAccess, _: Annotated[str, Depends(current_admin)]):
        return invoke(store.save_area, request.owner, request.readers)

    @router.post("/api/admin/shared-document-areas/preview")
    def preview_areas(request: ModulePreview, _: Annotated[str, Depends(current_admin)]):
        return {"items": invoke(store.list_documents, modules=request.modules),
                "areas": invoke(store.list_areas, modules=request.modules)}

    @router.get("/api/admin/shared-documents/{document_id}")
    def admin_document(document_id: str, _: Annotated[str, Depends(current_admin)]):
        return invoke(store.get_document, document_id, admin=True)[0]

    @router.patch("/api/admin/shared-documents/{document_id}")
    def edit(document_id: str, request: SharedDocumentPatch, _: Annotated[str, Depends(current_admin)]):
        return invoke(store.update_document, document_id, request.model_dump(exclude_unset=True))

    @router.get("/api/admin/shared-documents/{document_id}/file")
    def admin_download(document_id: str, _: Annotated[str, Depends(current_admin)]):
        path, filename, mime = invoke(store.document_file, document_id, admin=True)
        return FileResponse(path,filename=filename,media_type=mime,headers={"X-Content-Type-Options":"nosniff"})

    @router.post("/api/admin/shared-documents/{document_id}/retry", status_code=202)
    def retry(document_id: str, background_tasks: BackgroundTasks, _: Annotated[str, Depends(current_admin)]):
        invoke(store.request_retry, document_id)
        background_tasks.add_task(store.process_document, document_id, storage_root=shared_documents_root())
        return {"document_id":document_id,"status":"processing"}

    return RouterBundle(router, {})
