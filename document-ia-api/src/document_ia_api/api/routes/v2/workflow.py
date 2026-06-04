import logging
from typing import Optional
from uuid import UUID

from document_ia_api.api.auth import get_current_organization, verify_api_key
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.execution.response import ExecutionResponse
from document_ia_api.api.contracts.workflow_v2 import (
    WorkflowV2ExecuteResponse,
    WorkflowV2ListResponse,
    WorkflowV2OverridePayload,
)
from document_ia_api.api.mapper.workflow_v2_mapper import (
    map_workflow_v2_raw_list_to_contract,
)
from document_ia_api.api.middleware.rate_limiting_middleware import check_rate_limit
from document_ia_api.application.services.workflow_service import WorkflowService
from document_ia_api.application.services.workflow_v2_service import WorkflowV2Service
from document_ia_api.schemas.workflow import WorkflowExecutionDataV2
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.workflow.repository.workflow_v2_repository import (
    workflow_v2_repository,
)
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


async def _start_workflow_v2_execution(
    *,
    workflow_v2_service: WorkflowV2Service,
    organization_id: UUID,
    workflow_id: str,
    file: Optional[UploadFile],
    file_url: Optional[str],
    override: str | None,
    metadata: Optional[str],
) -> WorkflowExecutionDataV2:
    if (file is None and file_url is None) or (
        file is not None and file_url is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Exactly one of 'file' or 'file_url' must be provided.",
        )

    try:
        parsed_override = (
            WorkflowV2OverridePayload.model_validate_json(override)
            if override is not None
            else WorkflowV2OverridePayload.model_validate({})
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    workflow_id_normalized = workflow_id.strip()

    try:
        workflow_v2_service.validateWorkflow(
            workflow_id=workflow_id_normalized,
            override_payload=parsed_override,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to validate workflow v2 execute payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while validating workflow override",
        ) from exc

    return await workflow_v2_service.execute_workflow(
        organization_id=organization_id,
        workflow_id=workflow_id_normalized,
        file=file,
        file_url=file_url,
        metadata_json=metadata,
        override_payload=parsed_override,
    )


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


@router.post(
    "/{workflow_id}/execute",
    response_model=WorkflowV2ExecuteResponse,
    summary="Execute Workflow (v2)",
    description=(
        "Validate inputs and start a v2 workflow execution. "
        "The endpoint persists a started event containing the resolved workflow configuration "
        "(YAML defaults + request overrides), then publishes the execution message to Redis."
    ),
    responses={
        200: {
            "model": WorkflowV2ExecuteResponse,
            "description": "Workflow execution started successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "execution_id": "exec_123456789",
                            "workflow_id": "document-extraction-v2",
                            "organization_id": "11111111-1111-1111-1111-111111111111",
                            "status": "processing",
                            "created_at": "2026-05-19T10:30:00.000Z",
                            "file_info": None,
                            "file_url": "https://example.com/document.pdf",
                            "metadata": {"source": "api"},
                            "workflow_configuration": {
                                "id": "document-extraction-v2",
                                "name": "Document extraction v2 (Configurable)",
                                "version": "2.0.0",
                                "steps": [
                                    {"action": "download_file"},
                                    {
                                        "action": "llm_extract_data",
                                        "params": {
                                            "model": "albert-large",
                                            "temperature": 0.0,
                                            "document_type": "cni",
                                        },
                                    },
                                ],
                            },
                        },
                        "message": "Workflow execution started successfully",
                        "timestamp": "2026-05-19T10:30:00.000Z",
                    }
                }
            },
        },
        400: {
            "model": ProblemDetail,
            "description": "Bad Request (ProblemDetail) — invalid workflow override",
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail) — invalid API key",
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail) — API key not provided",
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail) — malformed multipart fields",
        },
        429: {
            "model": ProblemDetail,
            "description": "Too Many Requests (ProblemDetail) — rate limit exceeded",
        },
    },
    tags=["Workflows v2"],
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "Document file to process (optional if file_url is provided).",
                            },
                            "file_url": {
                                "type": "string",
                                "format": "uri",
                                "description": "URL of the document to process (optional if file is provided).",
                            },
                            "override": {
                                "type": "object",
                                "description": (
                                    "JSON object keyed by workflow step action. "
                                    "Each key maps to a list of {param, value} overrides."
                                ),
                                "additionalProperties": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "param": {
                                                "type": "string",
                                                "description": "Step parameter name to override",
                                            },
                                            "value": {
                                                "description": "Override value (string, number, boolean, list, object)",
                                            },
                                        },
                                        "required": ["param", "value"],
                                    },
                                },
                                "examples": {
                                    "simple": {
                                        "summary": "Simple extraction override",
                                        "value": {
                                            "llm_extract_data": [
                                                {
                                                    "param": "document_type",
                                                    "value": "passeport",
                                                }
                                            ]
                                        },
                                    },
                                    "classification": {
                                        "summary": "Classification + extraction overrides",
                                        "value": {
                                            "llm_classify_document": [
                                                {
                                                    "param": "document_types",
                                                    "value": ["cni", "passeport"],
                                                }
                                            ],
                                            "llm_extract_data": [
                                                {
                                                    "param": "model",
                                                    "value": "albert-small",
                                                }
                                            ],
                                        },
                                    },
                                },
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Optional free-form JSON object passed as execution metadata.",
                                "additionalProperties": True,
                                "example": {
                                    "source": "webhook",
                                    "priority": "high",
                                    "tags": ["lease", "urgent"],
                                },
                            },
                        },
                        "required": [],
                        "oneOf": [
                            {"required": ["file"]},
                            {"required": ["file_url"]},
                        ],
                    },
                    "encoding": {
                        "override": {
                            "contentType": "application/json",
                        },
                        "metadata": {
                            "contentType": "application/json",
                        },
                    },
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file_url": {
                                "type": "string",
                                "format": "uri",
                                "description": "URL of the document to process.",
                            },
                            "override": {
                                "type": "object",
                                "description": (
                                    "JSON object keyed by workflow step action. "
                                    "Each key maps to a list of {param, value} overrides."
                                ),
                                "additionalProperties": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "param": {
                                                "type": "string",
                                                "description": "Step parameter name to override",
                                            },
                                            "value": {
                                                "description": "Override value (string, number, boolean, list, object)",
                                            },
                                        },
                                        "required": ["param", "value"],
                                    },
                                },
                                "examples": {
                                    "simple": {
                                        "summary": "Simple extraction override",
                                        "value": {
                                            "llm_extract_data": [
                                                {
                                                    "param": "document_type",
                                                    "value": "passeport",
                                                }
                                            ]
                                        },
                                    },
                                    "classification": {
                                        "summary": "Classification + extraction overrides",
                                        "value": {
                                            "llm_classify_document": [
                                                {
                                                    "param": "document_types",
                                                    "value": ["cni", "passeport"],
                                                }
                                            ],
                                            "llm_extract_data": [
                                                {
                                                    "param": "model",
                                                    "value": "albert-small",
                                                }
                                            ],
                                        },
                                    },
                                },
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Optional free-form JSON object passed as execution metadata.",
                                "additionalProperties": True,
                                "example": {
                                    "source": "webhook",
                                    "priority": "high",
                                },
                            },
                        },
                        "required": [],
                        "oneOf": [
                            {"required": ["file_url"]},
                        ],
                    },
                },
            }
        }
    },
)
async def execute_workflow_v2(
    workflow_id: str = Path(..., description="ID of the workflow to execute"),
    file: Optional[UploadFile] = File(
        default=None,
        description="Document file to process (PDF, JPG, PNG, max 25MB)",
    ),
    file_url: Optional[str] = Form(
        default=None, description="URL of the document to process"
    ),
    override: str | None = Form(
        default=None,
        description=(
            "JSON object keyed by workflow step action, containing lists of "
            "{param, value} overrides."
        ),
    ),
    metadata: Optional[str] = Form(
        default=None,
        description="JSON string containing metadata object",
    ),
    api_key: str = Depends(verify_api_key),
    current_org: OrganizationDTO = Depends(get_current_organization),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> WorkflowV2ExecuteResponse:
    """Validate and start v2 workflow execution."""

    _ = (api_key, rate_limit_info)
    workflow_v2_service = WorkflowV2Service(db_session)

    try:
        execution_data = await _start_workflow_v2_execution(
            workflow_v2_service=workflow_v2_service,
            organization_id=current_org.id,
            workflow_id=workflow_id,
            file=file,
            file_url=file_url,
            override=override,
            metadata=metadata,
        )

        return WorkflowV2ExecuteResponse(
            status="success",
            data=execution_data,
            message="Workflow execution started successfully",
        )
    except HTTPException:
        await db_session.rollback()
        raise
    except RequestValidationError:
        await db_session.rollback()
        raise
    except Exception as exc:
        await db_session.rollback()
        logger.error("Failed to start workflow v2 execution: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while starting workflow execution",
        ) from exc


@router.post(
    "/{workflow_id}/execute-sync",
    response_model=ExecutionResponse,
    summary="Execute Workflow Synchronously (v2)",
    description=(
        "Validate inputs, start a v2 workflow execution, then wait until the execution reaches "
        "a terminal status (SUCCESS or FAILED), or timeout."
    ),
    responses={
        200: {
            "description": "Execution status retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "started": {
                            "summary": "Execution still started (if timeout window not elapsed yet in polling loop)",
                            "value": {
                                "id": "exec_123",
                                "status": "STARTED",
                                "data": {
                                    "created_at": "2026-05-19T10:30:00Z",
                                    "s3_file_info": None,
                                    "file_url": "https://example.com/document.pdf",
                                },
                            },
                        },
                        "success": {
                            "summary": "Completed execution (success)",
                            "value": {
                                "id": "exec_123",
                                "status": "SUCCESS",
                                "data": {
                                    "total_processing_time_ms": 1320,
                                    "result": {
                                        "classification": {
                                            "document_type": "CNI",
                                            "confidence": 0.94,
                                            "explanation": "Detected as CNI",
                                        },
                                        "extraction": {
                                            "type": "CNI",
                                            "properties": [
                                                {
                                                    "name": "first_name",
                                                    "value": "Alice",
                                                    "type": "string",
                                                }
                                            ],
                                        },
                                        "barcodes": [],
                                    },
                                },
                            },
                        },
                        "failed": {
                            "summary": "Execution failed",
                            "value": {
                                "id": "exec_123",
                                "status": "FAILED",
                                "data": {
                                    "error_type": "RuntimeError",
                                    "failed_step": "llm_extract_data",
                                    "retry_count": 1,
                                    "workflow_id": "document-extraction-v2",
                                    "error_message": "LLM timeout",
                                },
                            },
                        },
                    }
                }
            },
        },
        400: {
            "model": ProblemDetail,
            "description": "Bad Request (ProblemDetail) — invalid workflow override or invalid file/file_url combination",
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail) — invalid API key",
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail) — API key not provided",
        },
        408: {
            "model": ProblemDetail,
            "description": "Execution did not finish before timeout",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Request Timeout",
                        "status": 408,
                        "code": "workflow.timeout",
                        "detail": "Workflow execution did not finish before timeout",
                        "errors": {
                            "error": "sync_execution_timeout",
                            "execution_id": "exec_123",
                            "last_status": "STARTED",
                        },
                    }
                }
            },
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail) — malformed multipart fields",
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
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "Document file to process (optional if file_url is provided).",
                            },
                            "file_url": {
                                "type": "string",
                                "format": "uri",
                                "description": "URL of the document to process (optional if file is provided).",
                            },
                            "override": {
                                "type": "object",
                                "description": (
                                    "JSON object keyed by workflow step action. "
                                    "Each key maps to a list of {param, value} overrides."
                                ),
                                "additionalProperties": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "param": {
                                                "type": "string",
                                                "description": "Step parameter name to override",
                                            },
                                            "value": {
                                                "description": "Override value (string, number, boolean, list, object)",
                                            },
                                        },
                                        "required": ["param", "value"],
                                    },
                                },
                                "examples": {
                                    "simple": {
                                        "summary": "Simple extraction override",
                                        "value": {
                                            "llm_extract_data": [
                                                {
                                                    "param": "document_type",
                                                    "value": "passeport",
                                                }
                                            ]
                                        },
                                    },
                                    "classification": {
                                        "summary": "Classification + extraction overrides",
                                        "value": {
                                            "llm_classify_document": [
                                                {
                                                    "param": "document_types",
                                                    "value": ["cni", "passeport"],
                                                }
                                            ],
                                            "llm_extract_data": [
                                                {
                                                    "param": "model",
                                                    "value": "albert-small",
                                                }
                                            ],
                                        },
                                    },
                                },
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Optional free-form JSON object passed as execution metadata.",
                                "additionalProperties": True,
                                "example": {
                                    "source": "webhook",
                                    "priority": "high",
                                    "tags": ["lease", "urgent"],
                                },
                            },
                        },
                        "required": [],
                        "oneOf": [
                            {"required": ["file"]},
                            {"required": ["file_url"]},
                        ],
                    },
                    "encoding": {
                        "override": {
                            "contentType": "application/json",
                        },
                        "metadata": {
                            "contentType": "application/json",
                        },
                    },
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file_url": {
                                "type": "string",
                                "format": "uri",
                                "description": "URL of the document to process.",
                            },
                            "override": {
                                "type": "object",
                                "description": (
                                    "JSON object keyed by workflow step action. "
                                    "Each key maps to a list of {param, value} overrides."
                                ),
                                "additionalProperties": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "param": {
                                                "type": "string",
                                                "description": "Step parameter name to override",
                                            },
                                            "value": {
                                                "description": "Override value (string, number, boolean, list, object)",
                                            },
                                        },
                                        "required": ["param", "value"],
                                    },
                                },
                                "examples": {
                                    "simple": {
                                        "summary": "Simple extraction override",
                                        "value": {
                                            "llm_extract_data": [
                                                {
                                                    "param": "document_type",
                                                    "value": "passeport",
                                                }
                                            ]
                                        },
                                    }
                                },
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Optional free-form JSON object passed as execution metadata.",
                                "additionalProperties": True,
                                "example": {"source": "api", "priority": "high"},
                            },
                        },
                        "required": ["file_url"],
                    }
                },
            }
        }
    },
)
async def execute_workflow_v2_sync(
    workflow_id: str = Path(..., description="ID of the workflow to execute"),
    file: Optional[UploadFile] = File(
        default=None,
        description="Document file to process (PDF, JPG, PNG, max 25MB)",
    ),
    file_url: Optional[str] = Form(
        default=None, description="URL of the document to process"
    ),
    override: str | None = Form(
        default=None,
        description=(
            "JSON object keyed by workflow step action, containing lists of "
            "{param, value} overrides."
        ),
    ),
    metadata: Optional[str] = Form(
        default=None,
        description="JSON string containing metadata object",
    ),
    api_key: str = Depends(verify_api_key),
    current_org: OrganizationDTO = Depends(get_current_organization),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> ExecutionResponse:
    _ = (api_key, rate_limit_info)
    workflow_v2_service = WorkflowV2Service(db_session)
    workflow_service = WorkflowService(db_session)

    try:
        execution_data = await _start_workflow_v2_execution(
            workflow_v2_service=workflow_v2_service,
            organization_id=current_org.id,
            workflow_id=workflow_id,
            file=file,
            file_url=file_url,
            override=override,
            metadata=metadata,
        )

        await db_session.commit()

        return await workflow_service.wait_for_execution_result(
            execution_data.execution_id,
            current_org.id,
        )
    except HTTPException:
        await db_session.rollback()
        raise
    except RequestValidationError:
        await db_session.rollback()
        raise
    except Exception as exc:
        await db_session.rollback()
        logger.error("Failed to execute workflow v2 synchronously: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while executing workflow synchronously",
        ) from exc
