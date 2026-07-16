from fastapi import APIRouter

from document_ia_api.api.routes.v2.workflow import router as workflow_router

router = APIRouter(prefix="/v2")
router.include_router(workflow_router)
