import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import is_platform_admin
from document_ia_api.api.contracts.api_key.api_key import (
    APIKeyResult,
    APIKeyCreatedResult,
    UpdateAPIKeyStatusRequest,
)
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.api_key.api_key_service import ApiKeyService
from document_ia_infra.data.database import database_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/organizations/{organization_id}/api-keys",
    response_model=APIKeyCreatedResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    description=(
        "Create a new API key for a given organization (admin only).\n\n"
        "The returned 'key' contains the full presented key; store it securely — it won't be shown again."
    ),
    tags=["Admin", "API Keys"],
    responses={
        201: {
            "description": "API key created",
            "content": {
                "application/json": {
                    "example": {
                        "id": "8f2fdafb-9c2c-4a82-8a0e-7c7f12c9e111",
                        "prefix": "ABCD1234",
                        "key": "dia_dev_v1_ABCD1234_ABCDEFGHIJKLMNOPQRSTUVWX1234567890YZ12_IFZS",
                        "status": "Active",
                        "created_at": "2025-11-06T10:45:00Z",
                        "updated_at": "2025-11-06T10:45:00Z",
                    }
                }
            },
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail) — request schema validation errors",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Validation failed",
                        "status": 422,
                        "code": "validation.failed",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys",
                        "errors": {
                            "path": [
                                {
                                    "loc": ["path", "organization_id"],
                                    "msg": "value is not a valid uuid",
                                    "type": "type_error.uuid",
                                }
                            ]
                        },
                    }
                }
            },
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Unauthorized",
                        "status": 401,
                        "code": "http.unauthorized",
                        "detail": "Unauthorized",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys",
                    }
                }
            },
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Forbidden",
                        "status": 403,
                        "code": "http.forbidden",
                        "detail": "Admin role required",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys",
                    }
                }
            },
        },
        404: {
            "model": ProblemDetail,
            "description": "Organization not found (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Not Found",
                        "status": 404,
                        "code": "organization.not_found",
                        "detail": "Organization not found",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys",
                    }
                }
            },
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Internal Server Error",
                        "status": 500,
                        "code": "internal.error",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys",
                    }
                }
            },
        },
    },
)
async def create_api_key(
    organization_id: UUID = Path(..., description="Organization ID"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> APIKeyCreatedResult:
    try:
        key_service = ApiKeyService(db_session)
        return await key_service.create(organization_id)
    except HttpEntityNotFoundException:
        raise
    except Exception as err:
        logger.error(
            "Error creating API key for organization %s: %s", str(organization_id), err
        )
        raise


@router.put(
    "/organizations/{organization_id}/api-keys/{api_key_id}/status",
    response_model=APIKeyResult,
    summary="Update API key status",
    description=(
        "Update an API key status to one of: Active, Revoked, Expired (admin only)."
    ),
    tags=["Admin", "API Keys"],
    responses={
        200: {
            "description": "API key status updated",
            "content": {
                "application/json": {
                    "example": {
                        "id": "8f2fdafb-9c2c-4a82-8a0e-7c7f12c9e111",
                        "prefix": "ABCD1234",
                        "status": "Revoked",
                        "created_at": "2025-11-06T10:45:00Z",
                        "updated_at": "2025-11-06T12:00:00Z",
                    }
                }
            },
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail) — request schema validation errors",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Validation failed",
                        "status": 422,
                        "code": "validation.failed",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status",
                        "errors": {
                            "path": [
                                {
                                    "loc": ["path", "organization_id"],
                                    "msg": "value is not a valid uuid",
                                    "type": "type_error.uuid",
                                },
                                {
                                    "loc": ["path", "api_key_id"],
                                    "msg": "value is not a valid uuid",
                                    "type": "type_error.uuid",
                                },
                            ],
                            "body": [
                                {
                                    "loc": ["body", "status"],
                                    "msg": "Input should be 'Active' | 'Revoked' | 'Expired'",
                                    "type": "literal_error",
                                }
                            ],
                        },
                    }
                }
            },
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Unauthorized",
                        "status": 401,
                        "code": "http.unauthorized",
                        "detail": "Unauthorized",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status",
                    }
                }
            },
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Forbidden",
                        "status": 403,
                        "code": "http.forbidden",
                        "detail": "Admin role required",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status",
                    }
                }
            },
        },
        404: {
            "model": ProblemDetail,
            "description": "API key not found (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Not Found",
                        "status": 404,
                        "code": "api_key.not_found",
                        "detail": "API key not found",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status",
                    }
                }
            },
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Internal Server Error",
                        "status": 500,
                        "code": "internal.error",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status",
                    }
                }
            },
        },
    },
)
async def update_api_key_status(
    organization_id: UUID = Path(..., description="Organization ID"),
    api_key_id: UUID = Path(..., description="API key ID"),
    payload: UpdateAPIKeyStatusRequest = Body(...),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> APIKeyResult:
    try:
        api_key_service = ApiKeyService(db_session)
        return await api_key_service.update_status(
            organization_id, api_key_id, payload.status
        )
    except HttpEntityNotFoundException:
        raise
    except Exception as err:
        logger.error("Error updating API key status: %s", err)
        raise


@router.delete(
    "/organizations/{organization_id}/api-keys/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete API key",
    description="Delete an API key by ID (admin only).",
    tags=["Admin", "API Keys"],
    responses={
        204: {"description": "API key deleted"},
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Unauthorized",
                        "status": 401,
                        "code": "http.unauthorized",
                        "detail": "Unauthorized",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}",
                    }
                }
            },
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Forbidden",
                        "status": 403,
                        "code": "http.forbidden",
                        "detail": "Admin role required",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}",
                    }
                }
            },
        },
        404: {
            "model": ProblemDetail,
            "description": "API key not found (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Not Found",
                        "status": 404,
                        "code": "api_key.not_found",
                        "detail": "API key not found",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}",
                    }
                }
            },
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Internal Server Error",
                        "status": 500,
                        "code": "internal.error",
                        "instance": "/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}",
                    }
                }
            },
        },
    },
)
async def delete_api_key(
    organization_id: UUID = Path(..., description="Organization ID"),
    api_key_id: UUID = Path(..., description="API key ID"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> None:
    try:
        api_key_service = ApiKeyService(db_session)
        return await api_key_service.delete(organization_id, api_key_id)
    except HttpEntityNotFoundException:
        raise
    except Exception as err:
        logger.error("Error updating API key status: %s", err)
        raise
