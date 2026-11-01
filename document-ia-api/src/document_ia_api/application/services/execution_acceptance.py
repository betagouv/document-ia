"""Contrat d'acceptation partagé entre les exécutions de workflows v1 et v2.

Une exécution n'est annoncée comme acceptée que si son traitement est programmé
de façon récupérable. Lorsque la publication sur le stream Redis échoue, l'appelant
obtient une erreur `503` assortie d'un header `Retry-After`, et l'exécution déjà
créée est clôturée explicitement au lieu de rester indéfiniment en `STARTED`.

Voir l'issue #120 : ce module ne cherche pas à rendre atomiques Redis, PostgreSQL
et le stockage objet. Il garantit un état et une réponse cohérents avec la
programmation récupérable du traitement.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.redis.publisher import PublishFailedError
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.service.event_store_service import EventStoreService

logger = logging.getLogger(__name__)

# Code d'erreur fonctionnel exposé dans le corps RFC 7807 de la réponse 503.
EXECUTION_SCHEDULING_ERROR = "execution_scheduling_unavailable"


def scheduling_unavailable(execution_id: str) -> HTTPException:
    """Erreur HTTP renvoyée quand le traitement n'a pas pu être programmé."""
    return HTTPException(
        status_code=503,
        detail={
            "error": EXECUTION_SCHEDULING_ERROR,
            "message": (
                "The execution could not be scheduled. "
                "No processing is pending; retry the request."
            ),
            "execution_id": execution_id,
        },
        headers={
            "Retry-After": str(redis_settings.PUBLISH_RETRY_AFTER_SECONDS),
        },
    )


async def fail_unscheduled_execution(
    db_session: AsyncSession,
    *,
    execution_id: str,
    workflow_id: str,
    organization_id: UUID,
    error: PublishFailedError,
) -> None:
    """Clôturer une exécution dont le traitement n'a pas pu être programmé.

    L'événement de démarrage ayant déjà été persisté, on écrit un événement
    d'échec terminal : les lectures d'exécution doivent refléter l'absence de
    traitement programmé plutôt qu'un `STARTED` qui ne progressera jamais.

    L'échec de cette écriture est journalisé et ne masque pas l'erreur de
    programmation initiale : la réponse `503` reste la vérité du contrat.
    """
    try:
        event_store_service = EventStoreService(db_session)
        await event_store_service.emit_workflow_failed(
            workflow_id=workflow_id,
            execution_id=execution_id,
            organization_id=organization_id,
            error_type=EXECUTION_SCHEDULING_ERROR,
            error_message=(
                "Execution could not be scheduled on the processing stream; "
                "no processing is pending."
            ),
            failed_step="schedule",
        )
    except Exception:
        logger.exception(
            "Execution %s: unable to record the scheduling failure event",
            execution_id,
        )


def scheduling_log_context(error: PublishFailedError) -> dict[str, Any]:
    """Contexte de log sans contenu de document ni charge utile publiée."""
    return {"stream": error.stream_name, "reason": error.reason}
