import inspect
import json
import logging
import time
import uuid
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Tuple,
    Optional,
    Type,
    Set,
    get_origin,
    get_args,
    AsyncIterator,
    cast,
)

from fastapi import Request
from fastapi.params import Query as QueryParam, Path as PathParam, Form as FormParam
from pydantic import BaseModel
from pydantic.type_adapter import TypeAdapter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from document_ia_api.core.logging_setup import request_id_var, agg_buffer_var
from document_ia_infra.core.model.types.secret import (
    SecretPayloadStr,
    SecretPayloadBytes,
)
from document_ia_infra.core.util.resolve_root_folder import resolve_project_root

ROOT_FOLDER: Path = resolve_project_root("document_ia_api")
AGGREGATOR_OUTPUT_FILE: Path = ROOT_FOLDER / "logs" / "aggregator.jsonl"

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 4096  # prevent writing too much data inside the logs


def _unwrap_is_secret_type(tp: Any) -> bool:
    """Return True if the annotation corresponds to a Secret type (SecretStr/SecretBytes),
    possibly wrapped in Optional/Union/Annotated.
    """
    if tp is SecretPayloadStr or tp is SecretPayloadBytes:
        return True
    origin = get_origin(tp)
    if origin is None:
        return False
    # Annotated[Inner, ...]
    if origin is getattr(__import__("typing"), "Annotated", None):
        args = get_args(tp)
        return any(_unwrap_is_secret_type(a) for a in args)
    # Union / Optional
    if origin is getattr(__import__("typing"), "Union", None):
        args = get_args(tp)
        return any(_unwrap_is_secret_type(a) for a in args)
    return False


def _find_secret_params(request: Request) -> Tuple[Set[str], Set[str], Set[str]]:
    """Inspect the endpoint signature to find which query/path/form params are annotated as Secret types.
    Returns (secret_query_names, secret_path_names, secret_form_names) with external names (alias if set).
    """
    endpoint = request.scope.get("endpoint")
    if not endpoint:
        return set(), set(), set()
    secret_query: Set[str] = set()
    secret_path: Set[str] = set()
    secret_form: Set[str] = set()
    try:
        sig = inspect.signature(endpoint)
        for _, param in sig.parameters.items():
            ann = param.annotation
            if ann is inspect.Signature.empty:
                continue
            if not _unwrap_is_secret_type(ann):
                continue
            default = param.default
            ext_name = param.name
            # Resolve alias if provided (for Query/Path/Form, have .alias)
            alias = getattr(default, "alias", None)
            if isinstance(alias, str) and alias:
                ext_name = alias
            # Classify category
            if isinstance(default, QueryParam):
                secret_query.add(ext_name)
            elif isinstance(default, PathParam):
                secret_path.add(param.name)
            elif isinstance(default, FormParam):
                secret_form.add(ext_name)
    except Exception:
        return set(), set(), set()
    return secret_query, secret_path, secret_form


def _find_body_model_cls(request: Request) -> Optional[Type[BaseModel]]:
    endpoint = request.scope.get("endpoint")
    if not endpoint:
        return None
    try:
        sig = inspect.signature(endpoint)
        for _, param in sig.parameters.items():
            ann = param.annotation
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                return ann
    except Exception:
        return None
    return None


async def get_request_payload_safely(request: Request):
    """
    ⚠️ This function is called as a dependency in FastAPI routes.
    It reads the request body, so it must be used with care to avoid breaking the request
    Carefully read the request body and return a safe preview.
    - For JSON: try to parse into the endpoint's Pydantic model and serialize via model_dump(mode="json")
      (this automatically masks SecretStr/SecretBytes).
    - For application/x-www-form-urlencoded: return a truncated raw preview.
    - For multipart/form-data: list non-file fields (with secret fields masked) and represent files as masked
      entries with minimal metadata (filename/content_type).
    """
    try:
        content_type = request.headers.get("content-type", "").lower()
        secret_q, secret_p, secret_f = _find_secret_params(request)
        # Build masked query/path params
        masked_query = {
            k: ("**********" if k in secret_q else v)
            for k, v in dict(request.query_params).items()
        }
        masked_path = {
            k: ("**********" if k in secret_p else v)
            for k, v in dict(request.path_params).items()
        }
        base_info = {
            "query_params": masked_query,
            "path_params": masked_path,
        }

        if "multipart/form-data" in content_type:
            form = await request.form()
            preview: Dict[str, Any] = {}
            # Starlette's FormData preserves order of fields
            for key, value in form.items():
                # UploadFile-like: has filename and content_type attributes
                if hasattr(value, "filename") and hasattr(value, "content_type"):
                    fn = getattr(value, "filename", None)
                    ct = getattr(value, "content_type", None)
                    preview[key] = "********** (file)" if fn else "**********"
                    # Add minimal meta if available
                    meta_bits: List[str] = []
                    if fn:
                        meta_bits.append(f"name={fn}")
                    if ct:
                        meta_bits.append(f"type={ct}")
                    if meta_bits:
                        preview[key] += f" [{', '.join(meta_bits)}]"
                else:
                    text = str(value)
                    if key in secret_f:
                        preview[key] = "**********"
                    else:
                        # Truncate overly long fields to keep logs reasonable
                        preview[key] = (
                            text
                            if len(text) <= MAX_BODY_BYTES
                            else text[:MAX_BODY_BYTES] + "…"
                        )

            request.state.aggregator_payload = {
                **base_info,
                "body_preview": json.dumps(preview, ensure_ascii=False),
            }
            return

        if (
            content_type.startswith("application/json")
            or content_type.startswith("application/x-www-form-urlencoded")
            or content_type == ""
        ):
            body = await request.body()

            # If Json, try to parse with pydantic model to prevent liking secrets
            if content_type.startswith("application/json") and body:
                try:
                    model_cls = _find_body_model_cls(request)
                    if model_cls is not None:
                        instance = model_cls.model_validate_json(body)
                        preview_text = f"{instance.model_dump(mode='python')}"
                        request.state.aggregator_payload = {
                            **base_info,
                            "body_preview": preview_text,
                        }
                        return
                except Exception:
                    pass

            # Fallback: raw preview (truncated)
            preview_text = body[:MAX_BODY_BYTES].decode(errors="replace")
            request.state.aggregator_payload = {
                **base_info,
                "body_preview": preview_text,
            }
            return

        # Other type (e.g. application/octet-stream): do not read body
        request.state.aggregator_payload = {
            **base_info,
            "body_preview": f"<skipped: content-type {content_type}>",
        }
        return
    except Exception:
        request.state.aggregator_payload = {
            "query_params": dict(request.query_params),
            "path_params": dict(request.path_params),
            "body_preview": "<unavailable>",
        }


def _get_route_paths(request: Request) -> str:
    """Return (route_template).
    - normalized_path: the path with PathParam name, ex: "/api/v1/test/{test_param}" if available.
    """
    normalized_path = None
    route = request.scope.get("route")
    if route is not None:
        normalized_path = getattr(route, "path", None) or getattr(
            route, "path_format", None
        )
    if not normalized_path:
        normalized_path = request.url.path
    return normalized_path


def _get_response_type_adapter(request: Request) -> Optional[TypeAdapter[Any]]:
    """Try to build a TypeAdapter for the route's response type.
    Prefer APIRoute.response_model, fallback to endpoint return annotation.
    """
    try:
        route = request.scope.get("route")
        if route is not None:
            model = getattr(route, "response_model", None)
            if model is not None:
                try:
                    return TypeAdapter(model)
                except Exception:
                    pass
        endpoint = request.scope.get("endpoint")
        if endpoint is not None:
            sig = inspect.signature(endpoint)
            ret = sig.return_annotation
            if ret is not inspect.Signature.empty:
                try:
                    return TypeAdapter(ret)
                except Exception:
                    return None
    except Exception:
        return None
    return None


async def _wrap_response_and_capture(
    request: Request,
    response: Response,
) -> Tuple[Response, Dict[str, Any]]:
    """Consume the response body iterator to capture the payload, then rebuild a new Response.
    Prefer content sniffing. If payload is small and JSON, attempt to parse into the declared response model
    (response_model or return annotation) and dump via model_dump(mode="python") to mask secrets.
    """
    meta: Dict[str, Any] = {
        "status_code": getattr(response, "status_code", None),
        "media_type": getattr(response, "media_type", None),
        "headers": dict(response.headers),
    }
    try:
        body_bytes: bytes = b""
        iterator_obj = getattr(response, "body_iterator", None)
        if iterator_obj is not None:
            iterator = cast(AsyncIterator[bytes], iterator_obj)
            async for chunk in iterator:
                if chunk:
                    body_bytes += chunk
        else:
            # Non-streaming response: try to read raw body bytes
            raw_body = getattr(response, "body", None)
            if isinstance(raw_body, (bytes, bytearray)):
                body_bytes = bytes(raw_body)
            else:
                body_bytes = b""

        headers = dict(response.headers)
        headers.pop("content-length", None)
        new_response = Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=getattr(response, "background", None),
        )

        # Attempt typed parsing if small enough and looks like JSON
        stripped = body_bytes.lstrip() if body_bytes else b""
        is_small = len(body_bytes) <= MAX_BODY_BYTES
        if is_small and stripped.startswith((b"{", b"[")):
            try:
                adapter = _get_response_type_adapter(request)
                if adapter is not None:
                    typed_val = adapter.validate_json(body_bytes)
                    preview_obj = typed_val.model_dump()
                    meta["body_preview"] = f"{preview_obj}"
                    return new_response, meta
            except Exception:
                # fall back to generic preview below
                pass

        # Generic preview fallback
        ct_header = headers.get("content-type", "").lower()
        mt = (response.media_type or ct_header.split(";")[0]).strip()

        preview = f"<{mt or 'application/octet-stream'} {len(body_bytes)} bytes>"
        meta["body_preview"] = preview
        return new_response, meta
    except Exception:
        meta.setdefault("body_preview", "<unavailable>")
        return response, meta


class AggregationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        start = time.perf_counter()
        request_id = str(uuid.uuid4())

        # Initialize context vars
        token_rid = request_id_var.set(request_id)
        token_buf = agg_buffer_var.set([])

        request.state.request_id = request_id

        # Request informations
        req_info = {
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
            "headers": {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in {"authorization", "cookie"}
            },
        }

        try:
            # Execute the route and its dependencies;
            response = await call_next(request)

            # Get the query/path/body params captured by the dependency
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
                "method": req_info["method"],
                "path": req_info["path"],
                "normalized_path": normalized_path,
                "client": req_info["client"],
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
                "response_body_preview": resp_meta.get("body_preview", None),
                "logs": logs,
            }
            if query_payload:
                entry["query_params"] = query_payload.get("query_params")
                entry["path_params"] = query_payload.get("path_params")
                entry["request_body_preview"] = query_payload.get("body_preview")

            try:
                log_path = AGGREGATOR_OUTPUT_FILE
                # Ensure parent directory exists
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(AGGREGATOR_OUTPUT_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"Failed to write aggregator entry: {e}")

            return response

        finally:
            agg_buffer_var.reset(token_buf)
            request_id_var.reset(token_rid)
