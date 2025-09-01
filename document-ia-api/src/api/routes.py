from fastapi import APIRouter, Depends, UploadFile, File, Form
from .auth import verify_api_key
from .rate_limiting import check_rate_limit
from schemas.rate_limiting import RateLimitInfo
from .contracts.workflow import WorkflowExecuteResponse
from application.services.workflow_service import workflow_service
from datetime import datetime
from .config import settings

# Create router for API endpoints
router = APIRouter()


@router.get("/v1/")
async def get_api_status(
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
):
    """
    Get API status and information.

    This endpoint requires a valid API key in the Authorization header.

    Args:
        request: FastAPI request object
        api_key: The authenticated API key (automatically validated)

    Returns:
        dict: API status information
    """
    return {
        "status": "success",
        "message": "Document IA API is running",
        "version": settings.APP_VERSION,
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
        "version": settings.APP_VERSION,
    }


@router.post("/v1/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    file: UploadFile = File(
        ..., description="Document file to process (PDF, JPG, PNG)"
    ),
    metadata: str = Form(..., description="JSON string containing metadata object"),
    api_key: str = Depends(verify_api_key),
    rate_limit_info: RateLimitInfo = Depends(check_rate_limit),
) -> WorkflowExecuteResponse:
    """
    Execute a workflow with document upload and metadata processing.

    This endpoint accepts multipart form data with:
    - file: Document file (PDF, JPG, PNG, max 25MB)
    - metadata: JSON string containing metadata object

    Args:
        workflow_id: Unique identifier for the workflow to execute
        file: Document file to process
        metadata: JSON string containing metadata object
        api_key: The authenticated API key (automatically validated)

    Returns:
        WorkflowExecuteResponse: Execution status and file information

    Raises:
        400: Invalid request data, file validation error
        401: Invalid or missing API key
        404: Workflow not found
        413: File too large
        415: Unsupported file format
        429: Rate limit exceeded
        500: Internal server error
    """
    try:
        # Execute workflow using the service
        result = await workflow_service.execute_workflow(
            workflow_id=workflow_id, file=file, metadata_json=metadata
        )

        return WorkflowExecuteResponse(
            status="success",
            data=result,
            message="Workflow execution started successfully",
            timestamp=datetime.now().isoformat(),
        )

    except Exception:
        # Let the service handle specific HTTP exceptions
        raise
