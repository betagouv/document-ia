from fastapi import APIRouter
import logging

from document_ia_api.api.routes import router as main_router

# Configure logging
logger = logging.getLogger(__name__)

# Create router for API endpoints with comprehensive metadata
router = APIRouter()
# Add v1 router
router.include_router(main_router)
