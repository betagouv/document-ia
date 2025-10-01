from fastapi import APIRouter

from document_ia_api.api.routes.v1.workflow import router as workflow_router
from document_ia_api.api.routes.v1.health_check import router as health_check_router
from document_ia_api.api.routes.v1.executions import router as executions_router
from document_ia_api.api.routes.v1.test import router as test_router

router = APIRouter(prefix="/v1")
router.include_router(workflow_router)
router.include_router(executions_router)
router.include_router(health_check_router)
router.include_router(test_router)
