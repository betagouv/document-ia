from fastapi import APIRouter, Depends
from core.auth import verify_api_key
from datetime import datetime
from core.config import settings

# Create router for API endpoints
router = APIRouter()

@router.get("/v1/")
async def get_api_status(api_key: str = Depends(verify_api_key)):
    """
    Get API status and information.
    
    This endpoint requires a valid API key in the Authorization header.
    
    Args:
        api_key: The authenticated API key (automatically validated)
        
    Returns:
        dict: API status information
    """
    return {
        "status": "success",
        "message": "Document IA API is running",
        "version": settings.version,
    }


@router.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.
    
    Args:
        api_key: The authenticated API key (automatically validated)
        
    Returns:
        dict: Health status
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Document IA API",
        "version": settings.version
    }
