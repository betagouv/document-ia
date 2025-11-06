import logging
from uuid import UUID

from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import is_platform_admin
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.organization.organization import (
    OrganizationResult,
    OrganizationDetailsResult,
    CreateOrganizationRequest,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.organization.organization_service import (
    OrganizationService,
)
from document_ia_infra.data.database import database_manager
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/organizations",
    response_model=list[OrganizationResult],
    summary="List organizations",
    description="Get a list of all organizations (admin only).",
    tags=["Admin"],
    responses={
        200: {
            "description": "Organizations listed successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "sample": {
                            "summary": "Two organizations",
                            "value": [
                                {
                                    "id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                                    "name": "Document IA Default Organization",
                                    "contact_email": "admin@example.org",
                                    "platform_role": "PlatformAdmin",
                                    "created_at": "2025-11-06T10:30:00Z",
                                    "updated_at": "2025-11-06T11:00:00Z",
                                },
                                {
                                    "id": "4b0c9f2e-8b21-4a1d-9f0a-7a9a5cdef012",
                                    "name": "Acme Corp",
                                    "contact_email": "ops@acme.io",
                                    "platform_role": "Standard",
                                    "created_at": "2025-10-01T09:00:00Z",
                                    "updated_at": "2025-10-15T09:00:00Z",
                                },
                            ],
                        }
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
                        "instance": "/api/v1/admin/organizations",
                    }
                }
            },
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail) — require PlatformAdmin",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Forbidden",
                        "status": 403,
                        "code": "http.forbidden",
                        "detail": "Admin role required",
                        "instance": "/api/v1/admin/organizations",
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
                        "instance": "/api/v1/admin/organizations",
                    }
                }
            },
        },
    },
)
async def get_organization_list(
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> list[OrganizationResult]:
    """
    Admin endpoint to retrieve a list of all organizations.
    Only accessible by admin organization.
    """
    try:
        logger.info("Getting list of organizations")
        organization_service = OrganizationService(db_session)
        return await organization_service.get_all_organizations()
    except Exception as err:
        logger.error(f"Error retrieving organization list: {err}")
        raise err


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationDetailsResult,
    summary="Get organization details",
    description="Get organization details and attached API keys (admin only).",
    tags=["Admin"],
    responses={
        200: {
            "description": "Organization details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                        "name": "Document IA Default Organization",
                        "contact_email": "admin@example.org",
                        "platform_role": "PlatformAdmin",
                        "created_at": "2025-11-06T10:30:00Z",
                        "updated_at": "2025-11-06T11:00:00Z",
                        "api_keys": [
                            {
                                "id": "8f2fdafb-9c2c-4a82-8a0e-7c7f12c9e111",
                                "prefix": "ABCD1234",
                                "status": "Active",
                                "created_at": "2025-11-06T10:45:00Z",
                                "updated_at": "2025-11-06T10:45:00Z",
                            }
                        ],
                    }
                }
            },
        },
        401: {
            "model": ProblemDetail,
            "description": "Unauthorized (ProblemDetail)",
        },
        403: {
            "model": ProblemDetail,
            "description": "Forbidden (ProblemDetail)",
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
                        "instance": "/api/v1/admin/organizations/xxx",
                    }
                }
            },
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
        },
    },
)
async def get_organization_details(
    organization_id: UUID = Path(..., description="Organization id (UUID)"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> OrganizationDetailsResult:
    logger.info(f"Getting details of organization {organization_id}")

    try:
        service = OrganizationService(db_session)
        return await service.get_organization_details_by_id(str(organization_id))
    except HttpEntityNotFoundException:
        raise
    except Exception as err:
        logger.error(f"Error retrieving organization details: {err}")
        raise


@router.post(
    "/organizations",
    response_model=OrganizationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description=(
        "Create a new organization (admin only).\n\n"
        "Notes: platform_role accepts 'Standard' or 'PlatformAdmin'."
    ),
    tags=["Admin"],
    responses={
        201: {
            "description": "Organization created",
            "content": {
                "application/json": {
                    "example": {
                        "id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                        "name": "Acme Corp",
                        "contact_email": "ops@acme.io",
                        "platform_role": "Standard",
                        "created_at": "2025-11-06T10:30:00Z",
                        "updated_at": "2025-11-06T10:30:00Z",
                    }
                }
            },
        },
        400: {
            "model": ProblemDetail,
            "description": "Bad Request (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Bad Request",
                        "status": 400,
                        "code": "http.bad_request",
                        "detail": "Invalid payload: name and contact_email are required",
                        "instance": "/api/v1/admin/organizations",
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
                        "instance": "/api/v1/admin/organizations",
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
                        "instance": "/api/v1/admin/organizations",
                    }
                }
            },
        },
        409: {
            "model": ProblemDetail,
            "description": "Conflict (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Conflict",
                        "status": 409,
                        "code": "http.conflict",
                        "detail": "Organization with this email already exists",
                        "instance": "/api/v1/admin/organizations",
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
                        "instance": "/api/v1/admin/organizations",
                    }
                }
            },
        },
    },
)
async def create_organization(
    payload: CreateOrganizationRequest = Body(..., description="Organization payload"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> OrganizationResult:
    try:
        service = OrganizationService(db_session)
        return await service.create(
            name=payload.name,
            contact_email=payload.contact_email,
            platform_role=payload.platform_role,
        )
    except Exception as err:
        logger.error(f"Error creating organization: {err}")
        raise


@router.delete(
    "/organizations/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete organization",
    description=(
        "Delete an organization by ID (admin only).\n\n"
        "Cascades to dependent resources according to database constraints."
    ),
    tags=["Admin"],
    responses={
        204: {"description": "Organization deleted"},
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
                        "instance": "/api/v1/admin/organizations/{organization_id}",
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
                        "instance": "/api/v1/admin/organizations/{organization_id}",
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
                        "instance": "/api/v1/admin/organizations/{organization_id}",
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
                        "instance": "/api/v1/admin/organizations/{organization_id}",
                    }
                }
            },
        },
    },
)
async def delete_organization(
    organization_id: UUID = Path(..., description="Organization id (UUID)"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> None:
    try:
        service = OrganizationService(db_session)
        await service.delete(str(organization_id))
        return None
    except EntityNotFoundException:
        raise
    except Exception as err:
        logger.error(f"Error deleting organization: {err}")
        raise
