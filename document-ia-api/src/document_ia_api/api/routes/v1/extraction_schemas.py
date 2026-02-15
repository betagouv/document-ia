import logging

from document_ia_schemas import SupportedDocumentType, resolve_extract_schema
from fastapi import APIRouter
from fastapi import HTTPException, status

from document_ia_api.api.contracts.error.errors import AppError, ProblemDetail
from document_ia_api.api.contracts.extraction_schema import APIExtractionSchemaResult

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/extraction-schemas",
    response_model=list[APIExtractionSchemaResult],
    summary="Extraction",
    description="Get the json schemas for all extraction types",
    responses={
        200: {
            "model": list[APIExtractionSchemaResult],
            "description": "List of extraction schemas by document type",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "document_type": "cni",
                            "model": {
                                "title": "CNI Extract Schema",
                                "type": "object",
                                "properties": {
                                    "first_name": {"type": "string"},
                                    "last_name": {"type": "string"},
                                    "birth_date": {"type": "string", "format": "date"},
                                },
                                "required": ["first_name", "last_name"],
                            },
                        },
                        {
                            "document_type": "avis_imposition",
                            "model": {
                                "title": "Avis d'imposition Extract Schema",
                                "type": "object",
                                "properties": {
                                    "numero_fiscal": {"type": "string"},
                                    "reference_avis": {"type": "string"},
                                },
                                "required": ["numero_fiscal", "reference_avis"],
                            },
                        },
                    ],
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
                        "detail": "Internal Server Error - Get all extraction schemas failed with error: <message>",
                        "instance": "/api/v1/extraction-schemas",
                        "code": "http.error",
                    }
                }
            },
        },
    },
    tags=["Extraction"],
)
async def get_all_extraction_schemas() -> list[APIExtractionSchemaResult]:
    """
    Document endpoint for retreiving extraction schemas.

    **No Authentication Required**: This endpoint is publicly accessible for monitoring.

    """
    result: list[APIExtractionSchemaResult] = []
    try:
        for dt in SupportedDocumentType:
            value: str = str(dt.value)
            # Other is a generic type without a specific schema
            # Only used for classification fallback
            if dt == SupportedDocumentType.OTHER:
                continue
            extract_schema = resolve_extract_schema(value)
            result.append(
                APIExtractionSchemaResult(
                    document_type=value,
                    model=extract_schema.get_json_schema_dict(),
                )
            )
    except HTTPException:
        # Re-raise HTTP exceptions (like 503 above)
        raise
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Get all extractions schemas failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal Server Error - Get all extraction schemas failed with error: {e}",
        )

    return result
