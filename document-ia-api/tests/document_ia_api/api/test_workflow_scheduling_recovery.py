"""Test de bout en bout sur une vraie base : exécution non programmée (issue #120).

Le comportement du fichier et de l'événement de démarrage déjà créés est défini :
l'événement de démarrage est conservé (trace de la demande) et un événement
d'échec terminal clôt l'exécution. Un client qui relit l'exécution ne doit donc
jamais observer un `STARTED` définitif sans traitement programmé.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.redis.publisher import PublishFailedError


@pytest.mark.asyncio
async def test_unscheduled_execution_is_persisted_as_failed(
    client_with_api_key_standard, standard_api_key_value, organization_id
):
    """Après un 503, l'exécution persistée est `FAILED`, pas `STARTED`."""
    pdf = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"

    with patch(
        "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
        new=AsyncMock(return_value={"id": "document-classification-v1"}),
    ), patch(
        "document_ia_api.application.services.workflow_service.s3_service.upload_file",
        new=AsyncMock(return_value={"s3_key": "k", "presigned_url": "u"}),
    ), patch(
        "document_ia_api.application.services.workflow_service.Publisher.publish_message",
        new=AsyncMock(side_effect=PublishFailedError("event_stream", "no_connection")),
    ):
        response = client_with_api_key_standard.post(
            "/api/v1/workflows/document-classification-v1/execute",
            files={"file": ("test.pdf", pdf, "application/pdf")},
            data={"metadata": json.dumps({"source": "test"})},
            headers={"X-API-KEY": standard_api_key_value},
        )

    assert response.status_code == 503
    assert response.headers["Retry-After"]
    execution_id = response.json()["errors"]["execution_id"]

    # Redis a récupéré : une nouvelle tentative du client est acceptée et crée
    # une exécution distincte, sans collision avec l'exécution clôturée.
    with patch(
        "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
        new=AsyncMock(return_value={"id": "document-classification-v1"}),
    ), patch(
        "document_ia_api.application.services.workflow_service.s3_service.upload_file",
        new=AsyncMock(return_value={"s3_key": "k2", "presigned_url": "u2"}),
    ), patch(
        "document_ia_api.application.services.workflow_service.Publisher.publish_message",
        new=AsyncMock(return_value="2-0"),
    ) as publish_message:
        retry = client_with_api_key_standard.post(
            "/api/v1/workflows/document-classification-v1/execute",
            files={"file": ("test.pdf", pdf, "application/pdf")},
            data={"metadata": json.dumps({"source": "test"})},
            headers={"X-API-KEY": standard_api_key_value},
        )

    assert retry.status_code == 200
    retry_execution_id = retry.json()["data"]["execution_id"]
    assert retry_execution_id != execution_id
    assert retry.json()["data"]["status"] == "processing"
    # La nouvelle tentative programme bien un traitement.
    publish_message.assert_awaited_once()

    # Lecture de l'exécution initiale : elle est clôturée, pas bloquée en STARTED.
    with patch(
        "document_ia_api.api.routes.v1.executions.workflow_repository.get_workflow_by_id",
        new=AsyncMock(return_value={"id": "document-classification-v1"}),
    ):
        details = client_with_api_key_standard.get(
            f"/api/v1/executions/{execution_id}",
            headers={"X-API-KEY": standard_api_key_value},
        )

    assert details.status_code == 200, details.text
    assert details.json()["status"] == "FAILED"
