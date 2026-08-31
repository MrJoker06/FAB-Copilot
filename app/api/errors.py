from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ErrorDependencies:
    current_request_id: Callable[[], str | None]
    emit: Callable[..., None]


def error_payload(error_code: str, detail: str, retryable: bool = False, *, deps: ErrorDependencies, **extra) -> dict:
    return {"error_code": error_code, "detail": detail, "request_id": deps.current_request_id(), "retryable": retryable, **extra}


def http_problem(status_code: int, error_code: str, detail: str, retryable: bool = False) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": detail, "retryable": retryable})


def personal_problem(exc) -> HTTPException:
    return http_problem(exc.status_code, exc.error_code, exc.detail, exc.retryable)


def handlers(deps: ErrorDependencies):
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            detail = str(exc.detail.get("message") or "请求失败")
            error_code = str(exc.detail.get("error_code") or "HTTP_ERROR")
            retryable = bool(exc.detail.get("retryable", exc.status_code >= 500))
        else:
            detail = str(exc.detail)
            error_code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
            retryable = exc.status_code >= 500
        return JSONResponse(status_code=exc.status_code, content=error_payload(error_code, detail, retryable, deps=deps), headers=exc.headers)

    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(part) for part in item.get("loc", [])[1:]) for item in exc.errors()]
        return JSONResponse(status_code=422, content=error_payload("VALIDATION_ERROR", "请求参数不符合要求", False, deps=deps, fields=[field for field in fields if field]))

    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        request_id = deps.current_request_id() or f"error-{uuid.uuid4()}"
        deps.emit("api_exception", request_id, status="error", error_type=type(exc).__name__, full_content={"error_message": str(exc), "traceback": traceback.format_exc()})
        return JSONResponse(status_code=500, content=error_payload("INTERNAL_ERROR", "服务器内部错误", True, deps=deps))

    return handle_http_error, handle_validation_error, handle_unexpected_error
