import logging

import httpx

from document_ia_api.application.services.execution_service import ExecutionService
from document_ia_infra.data.database import database_manager
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.data.webhook.repository.webhook_repository import (
    WebHookRepository,
)
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_infra.redis.model.webhook_message import WebHookMessage

logger = logging.getLogger(__name__)


class WebhookNotificationService:
    def __init__(self):
        pass

    async def handle_webhook_notification(self, webhook_message: WebHookMessage):
        async with database_manager.local_session() as session:
            webhook_repo = WebHookRepository(session)
            event_repo = EventRepository(session)
            logger.info("Handling webhook notification: %s", webhook_message)
            try:
                current_web_hook = await webhook_repo.get_by_id(
                    webhook_message.webhook_id
                )
                event_dto = await event_repo.get_last_event_by_execution_id(
                    webhook_message.workflow_execution_id
                )
                if current_web_hook is None:
                    raise EntityNotFoundException(
                        entity_name="WebHook",
                        entity_id=str(webhook_message.webhook_id),
                    )
                if event_dto is None:
                    raise EntityNotFoundException(
                        entity_name="Event",
                        entity_id=str(webhook_message.workflow_execution_id),
                    )
                await self._call_webhook_notification(current_web_hook, event_dto)
            except Exception as e:
                logger.error("Error handling webhook notification: %s", e)
                raise e
            return

    async def _call_webhook_notification(
        self, webhook_dto: WebHookDTO, event_dto: EventDTO
    ):
        logger.info(
            "Sending webhook notification to %s for event %s",
            webhook_dto.url,
            event_dto.id,
        )
        execution_service = ExecutionService()

        # Préparer le body avec les données de l'événement
        payload = execution_service.get_event_model(
            event_dto, event_dto.execution_id, is_debug_mode=False
        )

        # Préparer les headers
        headers = {
            **webhook_dto.headers,  # Fusionner avec les headers personnalisés du webhook
            "Content-Type": "application/json",  # Always return application/json because we model_dump_json the content every time
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                webhook_dto.url,
                content=payload.model_dump_json(),
                headers=headers,
            )
            response.raise_for_status()
            logger.info(
                "Webhook notification sent successfully to %s with status %d",
                webhook_dto.url,
                response.status_code,
            )


webhook_notification_service = WebhookNotificationService()
