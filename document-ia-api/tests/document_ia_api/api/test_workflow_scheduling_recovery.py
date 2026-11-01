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
from fastapi.testclient import TestClient

from document_ia_infra.redis.publisher import PublishFailedError
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.data.database import database_manager  # noqa: F401
from tests.document_ia_api.conftest import create_test_app


@pytest.fixture(autouse=True)
def db_client(isolated_database_manager, mock_redis_service):
    """Client de test dont les sessions proviennent du manager isolé.

    Les routes reçoivent leur session via `Depends(database_manager.async_get_db)`,
    évalué à l'import : patcher l'attribut du module ne change donc rien. Seule
    une surcharge de dépendance FastAPI garantit que les lectures et écritures
    utilisent la base et la boucle d'événements du test.
    """
    import document_ia_api.api.middleware.rate_limiting_middleware as rl_mod

    original = rl_mod.redis_service
    rl_mod.redis_service = mock_redis_service
    app = create_test_app()
    app.dependency_overrides[database_manager.async_get_db] = (
        isolated_database_manager.async_get_db
    )
    yield TestClient(app)
    rl_mod.redis_service = original


@pytest.mark.asyncio
async def test_unscheduled_execution_is_persisted_as_failed(
    db_client, standard_api_key_value, organization_id
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
        response = db_client.post(
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
        retry = db_client.post(
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
        details = db_client.get(
            f"/api/v1/executions/{execution_id}",
            headers={"X-API-KEY": standard_api_key_value},
        )

    assert details.status_code == 200, details.text
    assert details.json()["status"] == "FAILED"


@pytest.mark.asyncio
async def test_unscheduled_v2_execution_remains_readable_as_failed(
    isolated_database_manager, organization_id
):
    """Une clôture v2 reste consultable : la version du workflow est préservée.

    La consultation choisit le dépôt de définitions d'après la version du
    dernier événement. Si la clôture était enregistrée en v1, l'exécution v2
    deviendrait introuvable au lieu d'être lisible en `FAILED`.

    Le test appelle les vrais services sur la base isolée, sans TestClient :
    celui-ci utiliserait une autre boucle d'événements que le manager de test.
    """
    from fastapi import HTTPException

    from document_ia_api.api.routes.v1.executions import get_execution
    from document_ia_api.application.services.workflow_v2_service import (
        WorkflowV2Service,
    )
    from document_ia_api.application.services.execution_service import (
        ExecutionService,
    )
    from document_ia_infra.service.event_store_service import EventStoreService

    raw_workflow = {
        "id": "document-extraction-v2",
        "steps": [
            {
                "action": "llm_classify_document",
                "params": {"document_types": {"default": "all"}},
            }
        ],
    }

    async with isolated_database_manager.local_session() as session:
        service = WorkflowV2Service(session)
        with patch(
            "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
            return_value=raw_workflow,
        ), patch.object(
            service.redis_producer,
            "publish_message",
            new=AsyncMock(
                side_effect=PublishFailedError("event_stream", "no_connection")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.execute_workflow(
                    organization_id=organization_id,
                    workflow_id="document-extraction-v2",
                    file=None,
                    file_url="https://example.com/document.pdf",
                    metadata_json=None,
                    override_payload=None,
                )

        assert exc_info.value.status_code == 503
        assert exc_info.value.headers["Retry-After"]
        execution_id = exc_info.value.detail["execution_id"]
        # Comportement de la route en cas d'erreur : la session est annulée.
        await session.rollback()

    # Le dernier événement persiste bien l'échec, dans la version du démarrage.
    async with isolated_database_manager.local_session() as session:
        last_event = await EventStoreService(
            session
        ).get_last_event_for_execution_id(execution_id)
        assert last_event.event.get("version") == 2

        # Consultation par la vraie fonction de route, avec les mêmes dépôts
        # simulés : seule la définition du workflow est fictive, la lecture des
        # événements et la projection de la réponse sont réelles.
        with patch(
            "document_ia_api.api.routes.v1.executions.workflow_v2_repository.get_raw_workflow_by_id",
            return_value=raw_workflow,
        ) as v2_lookup, patch(
            "document_ia_api.api.routes.v1.executions.workflow_repository.get_workflow_by_id",
            new=AsyncMock(return_value=None),
        ) as v1_lookup:
            organization = type(
                "Org", (), {"id": organization_id}
            )()
            details = await get_execution(
                execution_id=execution_id,
                organization=organization,
                db_session=session,
            )

        assert details.status == ExecutionStatus.FAILED
        v2_lookup.assert_called()
        v1_lookup.assert_not_called()
