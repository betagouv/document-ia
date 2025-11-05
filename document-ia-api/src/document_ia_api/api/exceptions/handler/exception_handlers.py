import logging
from http import HTTPStatus
from typing import Any, Optional, Dict, cast

from fastapi import Request, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from document_ia_api.api.config import settings
from document_ia_api.api.contracts.error.errors import ProblemDetail, AppError

logger = logging.getLogger(__name__)

HTTP_CODE_MAP = {
    400: "http.validation_error",
    401: "http.unauthorized",
    403: "http.forbidden",
    404: "http.not_found",
    405: "http.method_not_allowed",
    413: "http.payload_too_large",
    429: "http.rate_limited",
}


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase  # ex: "Not Found"
    except ValueError:
        return "HTTP Error"


def _split_http_detail(detail: Any) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Retourne (detail_str, errors_dict)
    """
    if isinstance(detail, str):
        return detail, None
    if isinstance(detail, dict):
        return None, cast(Dict[str, Any], detail)
    if detail is None:
        return None, None
    # fallback: on stringify
    return str(detail), None


def _problem_response(
    request: Request,
    *,
    status: int,
    title: str,
    detail: Optional[Any] = None,
    code: Optional[str] = None,
    type_: str = f"{settings.BASE_URL}/redoc",
    errors: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    trace_id = getattr(request.state, "request_id", None)
    body = ProblemDetail(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        instance=str(request.url.path),
        code=code,
        trace_id=trace_id,
        errors=errors,
    ).model_dump(exclude_none=True)
    return JSONResponse(status_code=status, content=body)


def setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> Response:  # pyright: ignore [reportUnusedFunction]
        return _problem_response(
            request,
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            code=exc.code,
            type_=exc.type_,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):  # pyright: ignore [reportUnusedFunction]
        # Mapper l’erreur FastAPI -> RFC7807
        logger.error(f"Validation Error {exc}")
        return _problem_response(
            request,
            status=422,
            title="Validation failed",
            errors={"__root__": exc.errors()},
            code="validation.failed",
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_error_handler(  # pyright: ignore [reportUnusedFunction]
        request: Request, exc: StarletteHTTPException
    ):
        # starlette HTTP exceptions to RFC7807
        title = _status_phrase(exc.status_code)
        detail, errors = _split_http_detail(exc.detail)

        return _problem_response(
            request,
            status=exc.status_code,
            title=title,
            detail=detail,
            code=HTTP_CODE_MAP.get(exc.status_code, "http.error"),
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):  # pyright: ignore [reportUnusedFunction]
        return _problem_response(
            request,
            status=500,
            title="Internal Server Error",
            code="internal.error",
        )
