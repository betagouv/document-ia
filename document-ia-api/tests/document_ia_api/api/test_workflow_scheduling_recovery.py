"""Test de bout en bout sur une vraie base : exécution non programmée (issue #120).

Le comportement du fichier et de l'événement de démarrage déjà créés est défini :
l'événement de démarrage est conservé (trace de la demande) et un événement
d'échec terminal clôt l'exécution. Un client qui relit l'exécution ne doit donc
jamais observer un `STARTED` définitif sans traitement programmé.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from document_ia_api.api.middleware.execution_admission import check_execution_admission
from document_ia_infra.redis.publisher import PublishFailedError
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.data.database import database_manager  # noqa: F401
from document_ia_api.schemas.workflow import WorkflowExecutionData
from tests.document_ia_api.conftest import create_test_app


@pytest.fixture(autouse=True)
def db_client(isolated_database_manager, mock_redis_service, monkeypatch):
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
    # This test exercises publication compensation on real PostgreSQL, not
    # admission. Inject capacity just like the standard route-client fixtures,
    # in both places the `execute` route can evaluate the preflight.
    app.dependency_overrides[check_execution_admission] = lambda: None
    admission_patch = ExitStack()
    for module in (
        "document_ia_api.api.routes.v1.workflow",
        "document_ia_api.api.routes.v2.workflow",
    ):
        admission_patch.enter_context(
            patch(f"{module}.check_execution_admission", new=AsyncMock())
        )
    redis_connection = AsyncMock(
        side_effect=AssertionError("Redis is outside this test boundary")
    )
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.redis_manager.get_connection",
        redis_connection,
    )
    app.dependency_overrides[database_manager.async_get_db] = (
        isolated_database_manager.async_get_db
    )
    # `EventStoreService` builds its own repository from the module-level manager,
    # not from the request dependency, so the isolated manager must be bound there
    # too: otherwise the second request reuses a pool attached to the first
    # request's event loop and the started event cannot be persisted.
    # The services import `database_manager` directly, so the isolated manager
    # must be bound in every module the request path resolves it through.
    for module in (
        "document_ia_infra.data.database",
        "document_ia_api.api.routes.v1.workflow",
        "document_ia_api.api.routes.v2.workflow",
        "document_ia_api.application.services.workflow_service",
        "document_ia_api.application.services.workflow_v2_service",
    ):
        try:
            monkeypatch.setattr(f"{module}.database_manager", isolated_database_manager)
        except AttributeError:
            pass
    yield TestClient(app)
    admission_patch.close()
    redis_connection.assert_not_awaited()
    rl_mod.redis_service = original


@pytest.mark.asyncio
async def test_unscheduled_execution_is_persisted_as_failed(
    isolated_database_manager, organization_id
):
    """Après un 503, l'exécution persistée est `FAILED`, pas `STARTED`.

    Appelle le vrai service sur la base isolée plutôt que `TestClient` : celui-ci
    ouvre une boucle d'événements par requête, et la seconde requête réutiliserait
    un pool asyncpg attaché à la première. L'événement de démarrage est désormais
    obligatoire, donc cette contrainte devient visible au lieu d'être masquée.
    """
    from document_ia_api.application.services.workflow_service import WorkflowService
    from document_ia_infra.redis.publisher import PublishFailedError

    organization_id_value = organization_id
    workflow_id = "document-classification-v1"

    async def start_execution(session) -> WorkflowExecutionData:
        service = WorkflowService(session)
        return await service.execute_workflow(
            organization_id=organization_id_value,
            workflow_id=workflow_id,
            file=None,
            file_url="https://example.com/doc.pdf",
            metadata_json=None,
            request_classification_parameter=None,
            request_extraction_parameter=None,
        )

    # 1. Publication indisponible : 503 et exécution clôturée.
    async with isolated_database_manager.local_session() as session:
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": workflow_id}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await start_execution(session)

    assert exc_info.value.status_code == 503
    # The failure records which execution was closed, so it can be read back.
    execution_id = exc_info.value.detail["execution_id"]

    # 2. Redis récupéré : une nouvelle tentative programme bien un traitement.
    async with isolated_database_manager.local_session() as session:
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": workflow_id}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(return_value="2-0"),
            ) as publish_message,
        ):
            retry = await start_execution(session)

    assert retry.status == "processing"
    publish_message.assert_awaited_once()
    assert retry.execution_id != execution_id

    # The first execution is closed, not left blocking readers as STARTED.
    from document_ia_infra.service.event_store_service import EventStoreService

    async with isolated_database_manager.local_session() as session:
        events = await EventStoreService(session).get_events_by_execution_id(
            execution_id
        )
    assert events[-1].event_type.value == "WorkflowExecutionFailed"


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
        with (
            patch(
                "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
                return_value=raw_workflow,
            ),
            patch.object(
                service.redis_producer,
                "publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
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
        last_event = await EventStoreService(session).get_last_event_for_execution_id(
            execution_id
        )
        assert last_event.event.get("version") == 2

        # Consultation par la vraie fonction de route, avec les mêmes dépôts
        # simulés : seule la définition du workflow est fictive, la lecture des
        # événements et la projection de la réponse sont réelles.
        with (
            patch(
                "document_ia_api.api.routes.v1.executions.workflow_v2_repository.get_raw_workflow_by_id",
                return_value=raw_workflow,
            ) as v2_lookup,
            patch(
                "document_ia_api.api.routes.v1.executions.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value=None),
            ) as v1_lookup,
        ):
            organization = type("Org", (), {"id": organization_id})()
            details = await get_execution(
                execution_id=execution_id,
                organization=organization,
                db_session=session,
            )

        assert details.status == ExecutionStatus.FAILED
        v2_lookup.assert_called()
        v1_lookup.assert_not_called()
