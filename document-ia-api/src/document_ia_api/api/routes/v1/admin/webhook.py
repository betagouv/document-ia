import logging
from uuid import UUID

from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.auth import is_platform_admin
from document_ia_api.api.contracts.error.errors import ProblemDetail
from document_ia_api.api.contracts.webhook.webhook import (
    WebHookResult,
    CreateWebHookRequest,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.webhook.webhook_service import WebHookService
from document_ia_infra.data.database import database_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Admin"],
)


@router.get(
    "/organizations/{organization_id}/webhooks",
    response_model=list[WebHookResult],
    summary="List webhooks for an organization",
    description=(
        "Retrieve all webhooks belonging to the specified organization (admin only)."
    ),
    responses={
        200: {
            "description": "Webhooks listed successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "empty": {"summary": "No webhooks", "value": []},
                        "sample": {
                            "summary": "Two webhooks",
                            "value": [
                                {
                                    "id": "9b1d4c2e-7a12-4f3a-8b1d-001122334455",
                                    "organization_id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                                    "url": "https://example.com/webhook/a",
                                    "headers": {"X-Signature": "abc123"},
                                    "created_at": "2025-11-06T10:30:00Z",
                                    "updated_at": "2025-11-06T10:30:00Z",
                                },
                                {
                                    "id": "2e4d9a7c-1b2f-4a8e-9f0a-667788990011",
                                    "organization_id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                                    "url": "https://example.com/webhook/b",
                                    "headers": {"X-Auth": "token"},
                                    "created_at": "2025-11-06T11:00:00Z",
                                    "updated_at": "2025-11-06T11:15:00Z",
                                },
                            ],
                        },
                    }
                }
            },
        },
        401: {"model": ProblemDetail, "description": "Unauthorized (ProblemDetail)"},
        403: {"model": ProblemDetail, "description": "Forbidden (ProblemDetail)"},
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
                        "instance": "/api/v1/admin/organizations/{organization_id}/webhooks",
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
async def list_webhooks(
    organization_id: UUID = Path(..., description="Organization id (UUID)"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> list[WebHookResult]:
    logger.info(f"Listing webhooks for organization {organization_id}")
    try:
        service = WebHookService(db_session)
        return await service.list_by_organization(organization_id)
    except Exception as err:
        logger.error(f"Error listing webhooks: {err}")
        raise


@router.post(
    "/organizations/{organization_id}/webhooks",
    response_model=WebHookResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create webhook for an organization",
    description="Create a webhook associated to the organization (admin only).",
    responses={
        201: {
            "description": "Webhook created",
            "content": {
                "application/json": {
                    "example": {
                        "id": "9b1d4c2e-7a12-4f3a-8b1d-001122334455",
                        "organization_id": "c3f38a34-4c9b-4f0c-8b1d-2c2ce2123456",
                        "url": "https://example.com/webhook/a",
                        "headers": {"X-Signature": "abc123"},
                        "created_at": "2025-11-06T10:30:00Z",
                        "updated_at": "2025-11-06T10:30:00Z",
                    }
                }
            },
        },
        400: {
            "model": ProblemDetail,
            "description": "Invalid data (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Bad Request",
                        "status": 400,
                        "code": "webhook.invalid",
                        "detail": "Webhook URL is invalid",
                        "instance": "/api/v1/admin/organizations/{organization_id}/webhooks",
                    }
                }
            },
        },
        401: {"model": ProblemDetail, "description": "Unauthorized (ProblemDetail)"},
        403: {"model": ProblemDetail, "description": "Forbidden (ProblemDetail)"},
        404: {
            "model": ProblemDetail,
            "description": "Organization not found (ProblemDetail)",
        },
        422: {
            "model": ProblemDetail,
            "description": "Validation failed (ProblemDetail)",
        },
        500: {
            "model": ProblemDetail,
            "description": "Internal Server Error (ProblemDetail)",
        },
    },
)
async def create_webhook(
    organization_id: UUID = Path(..., description="Organization id (UUID)"),
    payload: CreateWebHookRequest = Body(..., description="Webhook payload"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> WebHookResult:
    logger.info(f"Creating webhook for organization {organization_id}")
    try:
        service = WebHookService(db_session)
        return await service.create(
            organization_id=organization_id,
            url=payload.url,
            headers=payload.headers or {},
        )
    except Exception as err:
        logger.error(f"Error creating webhook: {err}")
        raise


@router.delete(
    "/organizations/{organization_id}/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete webhook",
    description="Delete a webhook by id (admin only).",
    responses={
        204: {"description": "Webhook deleted"},
        401: {"model": ProblemDetail, "description": "Unauthorized (ProblemDetail)"},
        403: {"model": ProblemDetail, "description": "Forbidden (ProblemDetail)"},
        404: {
            "model": ProblemDetail,
            "description": "Webhook not found (ProblemDetail)",
            "content": {
                "application/json": {
                    "example": {
                        "type": "about:blank",
                        "title": "Not Found",
                        "status": 404,
                        "code": "webhook.not_found",
                        "detail": "Webhook not found",
                        "instance": "/api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}",
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
async def delete_webhook(
    organization_id: UUID = Path(..., description="Organization id (UUID)"),
    webhook_id: UUID = Path(..., description="Webhook id (UUID)"),
    _=Depends(is_platform_admin),
    db_session: AsyncSession = Depends(database_manager.async_get_db),
) -> None:
    logger.info(f"Deleting webhook {webhook_id} for organization {organization_id}")
    try:
        service = WebHookService(db_session)
        await service.delete(webhook_id)
        return None
    except HttpEntityNotFoundException:
        raise
    except Exception as err:
        logger.error(f"Error deleting webhook: {err}")
        raise
