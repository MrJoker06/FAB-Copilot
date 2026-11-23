"""Page API for lot commonality analyses; every entry re-authorizes the current principal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.tools.lot_commonality.contracts import (
    LotCommonalityAccessError,
    LotCommonalityDataError,
    LotCommonalityInputError,
)
from app.tools.lot_commonality.service import LotCommonalityResultError, LotCommonalityService

from .runtime import NamespaceProvider, RouterBundle

_RESULT_STATUS = {
    "RESULT_UNAVAILABLE": 404,
    "RESULT_CURSOR_INVALID": 400,
    "RESULT_STORAGE_LIMIT": 507,
    "RESULT_STORE_UNAVAILABLE": 503,
}


def _problem(status: int, code: str, detail: str, *, retryable: bool = False, context=None) -> HTTPException:
    payload: dict[str, Any] = {"error_code": code, "message": detail, "retryable": retryable}
    if context is not None:
        payload["context"] = context
    return HTTPException(status_code=status, detail=payload)


def _call(operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except LotCommonalityInputError as exc:
        raise _problem(422, exc.error_code, exc.detail, context=exc.context) from None
    except LotCommonalityAccessError as exc:
        raise _problem(403, exc.error_code, exc.detail) from None
    except LotCommonalityDataError as exc:
        raise _problem(502, exc.error_code, exc.detail) from None
    except LotCommonalityResultError as exc:
        raise _problem(
            _RESULT_STATUS[exc.error_code], exc.error_code, exc.detail,
            retryable=exc.error_code == "RESULT_STORE_UNAVAILABLE",
        ) from None


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def service_factory() -> LotCommonalityService:
        return deps()["lot_commonality_service"]()

    def current_principal() -> Any:
        return deps()["current_principal"]()

    def create_lot_commonality_analysis(payload: Any = Body(...)) -> dict:
        return _call(lambda: service_factory().create(payload, current_principal()))

    def read_lot_commonality_analysis(analysis_ref: str) -> dict:
        return _call(lambda: service_factory().read(analysis_ref, current_principal()))

    def read_lot_commonality_members(analysis_ref: str, payload: Any = Body(...)) -> dict:
        return _call(lambda: service_factory().members(analysis_ref, payload, current_principal()))

    def read_lot_commonality_records(analysis_ref: str, payload: Any = Body(...)) -> dict:
        return _call(lambda: service_factory().records(analysis_ref, payload, current_principal()))

    base = "/api/lot-commonality/analyses"
    router = APIRouter()
    router.add_api_route(base, create_lot_commonality_analysis, methods=["POST"])
    router.add_api_route(base + "/{analysis_ref}", read_lot_commonality_analysis, methods=["GET"])
    router.add_api_route(base + "/{analysis_ref}/members", read_lot_commonality_members, methods=["POST"])
    router.add_api_route(base + "/{analysis_ref}/records", read_lot_commonality_records, methods=["POST"])
    return RouterBundle(
        router,
        {
            "create_lot_commonality_analysis": create_lot_commonality_analysis,
            "read_lot_commonality_analysis": read_lot_commonality_analysis,
            "read_lot_commonality_members": read_lot_commonality_members,
            "read_lot_commonality_records": read_lot_commonality_records,
        },
    )
