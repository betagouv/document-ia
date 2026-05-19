import logging

from fastapi import APIRouter, Depends, HTTPException, status

from document_ia_api.api.auth import verify_api_key
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.workflow_v2 import WorkflowV2ListResponse
from document_ia_api.api.mapper.workflow_v2_mapper import (
    map_workflow_v2_raw_list_to_contract,
)
from document_ia_api.api.middleware.rate_limiting_middleware import check_rate_limit
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_infra.data.workflow.repository.workflow_v2_repository import (
    workflow_v2_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.get(
    "/",
    response_model=WorkflowV2ListResponse,
    response_model_exclude_none=True,
    summary="List Available Workflows (v2)",
    description=(
        "Return the list of workflow definitions available on the API. "
        "Definitions are loaded from the workflow v2 YAML repository and include global metadata "
        "(id, name, version, limits) plus step-by-step parameter rules."
    ),
    responses={
        200: {
            "model": WorkflowV2ListResponse,
            "description": "Available workflows retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": [
                            {
                                "id": "document-extraction-v2",
                                "name": "Document extraction v2 (Configurable)",
                                "description": "Workflow generique avec surcharge des parametres OCR et LLM.",
                                "version": "2.0.0",
                                "enabled": True,
                                "supported_file_types": [
                                    "application/pdf",
                                    "image/jpeg",
                                    "image/png",
                                ],
                                "max_file_size_mb": 25,
                                "processing_timeout_minutes": 5,
                                "steps": [
                                    {"action": "download_file", "params": {}},
                                    {
                                        "action": "llm_extract_data",
                                        "params": {
                                            "model": {
                                                "type": "string",
                                                "default": "albert-large",
                                                "enum": [
                                                    "albert-large",
                                                    "albert-small",
                                                ],
                                            }
                                        },
                                    },
                                ],
                            }
                        ],
                        "message": "Available workflows retrieved successfully",
                        "timestamp": "2026-05-19T10:30:00.000Z",
                    }
                }
            },
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail) — invalid API key",
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail) — Api key not provided",
        },
        429: {
            "model": ProblemDetail,
            "description": "Too Many Requests (ProblemDetail) — rate limit exceeded",
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
        },
    },
    tags=["Workflows v2"],
)
async def list_available_workflows(
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
) -> WorkflowV2ListResponse:
    """Return all available workflow v2 definitions.

    **Authentication Required**: This endpoint requires a valid API key in `X-API-KEY`.

    **Rate Limiting**: This endpoint is subject to per-key rate limits.

    The returned payload is intentionally close to the YAML configuration so clients can
    dynamically render available workflows and their configurable parameters.
    """

    _ = (
        api_key,
        rate_limit_info,
    )  # Explicitly keep dependencies as used for linting clarity.

    try:
        workflows_raw = workflow_v2_repository.get_raw_workflows()
        workflows_contract = map_workflow_v2_raw_list_to_contract(workflows_raw)
        logger.info(
            "Workflow v2 list requested",
            extra={
                "endpoint": "list_available_workflows",
                "workflow_count": len(workflows_raw),
            },
        )

        return WorkflowV2ListResponse(
            status="success",
            data=workflows_contract,
            message="Available workflows retrieved successfully",
        )
    except Exception as exc:
        logger.error("Failed to list workflows v2: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve available workflows",
        ) from exc
