import logging

from fastapi import APIRouter, Query, Body, Path

from document_ia_api.api.contracts.test import TestRequest, TestResponse
from document_ia_infra.core.model.types.secret import SecretPayloadStr

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get(
    "/test/{test_param}",
    summary="Test endpoint",
    description="Endpoint de test qui lit un paramètre de requête 'test-id' et un body JSON (id, description).",
    tags=["Test"],
)
async def get_test(
    test_param: str = Path(
        ..., alias="test_param", description="Paramètre de test passé dans le chemin"
    ),
    test_id: str = Query(
        ..., alias="test-id", description="Identifiant de test passé dans l'URL"
    ),
    secret_param: SecretPayloadStr = Query(
        ..., alias="secret_param", description="Identifiant de test passé dans l'URL"
    ),
    payload: TestRequest = Body(..., description="Corps JSON avec id et description"),
) -> TestResponse:
    logger.info(f"Testing {payload}")

    return TestResponse(
        status="ok",
        test_param=test_param,
        test_id=test_id,
        secret_param=secret_param,
        payload=payload,
    )
