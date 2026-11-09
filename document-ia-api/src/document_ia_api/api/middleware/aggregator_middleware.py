import json
import logging
import time
import types as _pytypes
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    get_args,
    get_origin,
)

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from document_ia_api.core.logging_setup import agg_buffer_var, request_id_var
from document_ia_infra.core.model.types.secret import (
    SecretPayloadBytes,
    SecretPayloadStr,
)
from document_ia_infra.core.security.safe_logging import (
    ALLOWED_PATH_PARAMS,
    ALLOWED_QUERY_PARAMS,
    ALLOWED_REQUEST_HEADERS,
    ALLOWED_RESPONSE_HEADERS,
    filter_headers,
    filter_path_params,
    filter_query_params,
)
from pydantic import SecretBytes as _PydSecretBytes, SecretStr as _PydSecretStr

logger = logging.getLogger(__name__)


def _unwrap_is_secret_type(tp: Any) -> bool:
    """Return True if the annotation corresponds to a secret payload type,
    supporting wrappers like Annotated[...] and Union/Optional.
    Recognizes SecretPayloadStr/Bytes aliases and underlying Pydantic SecretStr/SecretBytes.
    """
    if tp is SecretPayloadStr or tp is SecretPayloadBytes:
        return True

    while True:
        origin = get_origin(tp)
        if origin is getattr(__import__("typing"), "Annotated", None):
            args = get_args(tp)
            if not args:
                break
            tp = args[0]
            continue
        if origin in (
            getattr(__import__("typing"), "Union", None),
            getattr(_pytypes, "UnionType", None),
        ):
            return any(
                _unwrap_is_secret_type(t) for t in get_args(tp) if t is not type(None)
            )
        break

    try:
        if tp is _PydSecretStr or tp is _PydSecretBytes:
            return True
    except Exception:
        pass
    return False


async def get_request_payload_safely(request: Request) -> None:
    """FastAPI route dependency that captures request query, path, and envelope metadata safely.

    Strictly applies positive allowlists for headers and parameters.
    Never stores raw body previews or unmasked parameters.
    """
    try:
        masked_query = filter_query_params(
            dict(request.query_params), ALLOWED_QUERY_PARAMS
        )
        masked_path = filter_path_params(dict(request.path_params), ALLOWED_PATH_PARAMS)

        content_type = request.headers.get("content-type")
        content_length_hdr = request.headers.get("content-length")
        body_len: Optional[int] = (
            int(content_length_hdr)
            if content_length_hdr and content_length_hdr.isdigit()
            else None
        )

        # For non-streaming, non-multipart JSON or form requests with unknown length, read length
        if (
            body_len is None
            and "multipart/form-data" not in (content_type or "").lower()
        ):
            try:
                body_bytes = await request.body()
                body_len = len(body_bytes)
            except Exception:
                pass

        request_body_info: Optional[Dict[str, Any]] = None
        if content_type or body_len is not None:
            request_body_info = {
                "content_type": content_type or "unknown",
                "bytes": body_len if body_len is not None else 0,
            }

        request.state.aggregator_payload = {
            "query_params": masked_query,
            "path_params": masked_path,
            "request_body": request_body_info,
        }
    except Exception:
        request.state.aggregator_payload = {
            "query_params": filter_query_params(dict(request.query_params)),
            "path_params": filter_path_params(dict(request.path_params)),
            "request_body": None,
        }


def _get_route_paths(request: Request) -> str:
    """Return route template or URL path."""
    normalized_path = None
    route = request.scope.get("route")
    if route is not None:
        normalized_path = getattr(route, "path", None) or getattr(
            route, "path_format", None
        )
    if not normalized_path:
        normalized_path = request.url.path
    return normalized_path


async def _wrap_response_and_capture(
    request: Request,
    response: Response,
) -> Tuple[Response, Dict[str, Any]]:
    """Capture response envelope metadata safely without consuming streaming bodies."""
    resp_headers = filter_headers(dict(response.headers), ALLOWED_RESPONSE_HEADERS)
    resp_ct = response.headers.get("content-type") or getattr(
        response, "media_type", None
    )
    resp_cl = response.headers.get("content-length")
    resp_bytes: Optional[int] = int(resp_cl) if resp_cl and resp_cl.isdigit() else None

    if (
        resp_bytes is None
        and hasattr(response, "body")
        and isinstance(response.body, (bytes, bytearray))
    ):
        resp_bytes = len(response.body)

    resp_body_meta: Optional[Dict[str, Any]] = None
    if resp_ct or resp_bytes is not None:
        resp_body_meta = {
            "content_type": resp_ct or "unknown",
            "bytes": resp_bytes if resp_bytes is not None else 0,
        }

    meta: Dict[str, Any] = {
        "status_code": getattr(response, "status_code", None),
        "media_type": getattr(response, "media_type", None),
        "response_headers": resp_headers,
        "response_body": resp_body_meta,
    }
    return response, meta


class AggregationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        start = time.perf_counter()
        request_id = getattr(request.state, "request_id", None) or request.headers.get(
            "x-request-id", "unknown"
        )

        # Initialize context vars
        token_rid = request_id_var.set(request_id)
        token_buf = agg_buffer_var.set([])

        req_headers = filter_headers(dict(request.headers), ALLOWED_REQUEST_HEADERS)

        try:
            response = await call_next(request)

            query_payload: Dict[str, Any] = (
                getattr(request.state, "aggregator_payload", {}) or {}
            )

            response, resp_meta = await _wrap_response_and_capture(request, response)
            status_code = resp_meta.get(
                "status_code", getattr(response, "status_code", None)
            )
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

            logs: List[Dict[str, Any]] = agg_buffer_var.get() or []
            normalized_path = _get_route_paths(request)

            entry: Dict[str, Any] = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "normalized_path": normalized_path,
                "client": request.client.host if request.client else None,
                "headers": req_headers,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
                "response_headers": resp_meta.get("response_headers", {}),
                "logs": logs,
            }

            if query_payload:
                entry["query_params"] = query_payload.get("query_params", {})
                entry["path_params"] = query_payload.get("path_params", {})
                if query_payload.get("request_body") is not None:
                    entry["request_body"] = query_payload["request_body"]
            else:
                entry["query_params"] = filter_query_params(dict(request.query_params))
                entry["path_params"] = filter_path_params(dict(request.path_params))
                ct = request.headers.get("content-type")
                cl = request.headers.get("content-length")
                b_len = int(cl) if cl and cl.isdigit() else None
                if ct or b_len is not None:
                    entry["request_body"] = {
                        "content_type": ct or "unknown",
                        "bytes": b_len if b_len is not None else 0,
                    }

            if resp_meta.get("response_body") is not None:
                entry["response_body"] = resp_meta["response_body"]

            try:
                tags = {
                    "logger": "aggregator",
                    "format": "json",
                    "status_code": str(status_code),
                    "normalized_path": normalized_path,
                    "method": request.method,
                }

                organization = getattr(request.state, "organization", None)
                if organization is not None and hasattr(organization, "id"):
                    tags["organization_id"] = str(organization.id)

                agg_logger = logging.getLogger("aggregator")
                agg_logger.info(json.dumps(entry), extra={"tags": tags})
            except Exception as e:
                logger.error(f"Failed to log aggregation entry: {e}")

            return response

        finally:
            agg_buffer_var.reset(token_buf)
            request_id_var.reset(token_rid)
