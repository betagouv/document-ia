from fastapi import APIRouter
from document_ia_api.api.routes.v1.admin.organization import (
    router as organization_routeur,
)
from document_ia_api.api.routes.v1.admin.api_key import router as api_key_routeur

router = APIRouter(prefix="/admin")
router.include_router(organization_routeur)
router.include_router(api_key_routeur)
