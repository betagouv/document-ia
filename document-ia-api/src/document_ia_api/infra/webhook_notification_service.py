import asyncio
import logging

import httpx
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as SATimeoutError,
)

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
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.model.webhook_message import WebHookMessage

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({408, 409, 425, 429})


class WebhookNotificationService:
    def __init__(
        self,
        *,
        retry_initial_delay_seconds: float = 5.0,
        retry_backoff_multiplier: float = 2.0,
        max_retry_delay_seconds: float = 30.0,
        http_timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.retry_initial_delay_seconds = retry_initial_delay_seconds
        self.retry_backoff_multiplier = retry_backoff_multiplier
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.http_timeout_seconds = http_timeout_seconds
        self._http_client: httpx.AsyncClient | None = http_client
        self._owns_http_client = http_client is None
        self._stop_event: asyncio.Event | None = None
        self._execution_service = ExecutionService()

    def bind_stop_event(self, stop_event: asyncio.Event | None) -> None:
        """Associe le signal d'arrêt du consumer pour écourter proprement les backoffs."""
        self._stop_event = stop_event

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.http_timeout_seconds)
            self._owns_http_client = True
        return self._http_client

    async def aclose(self) -> None:
        if (
            self._owns_http_client
            and self._http_client is not None
            and not self._http_client.is_closed
        ):
            await self._http_client.aclose()
        self._http_client = None

    @staticmethod
    def should_retry_http_status(status_code: int) -> bool:
        if status_code in RETRYABLE_HTTP_STATUSES:
            return True
        return 500 <= status_code < 600

    def compute_backoff_delay(self, retry_count: int) -> float:
        if self.retry_initial_delay_seconds <= 0:
            return 0.0
        raw_delay = self.retry_initial_delay_seconds * (
            self.retry_backoff_multiplier ** max(0, retry_count)
        )
        return min(raw_delay, self.max_retry_delay_seconds)

    async def _sleep_before_retry(
        self, *, retry_count: int, is_last_retry: bool
    ) -> None:
        if is_last_retry:
            return
        delay = self.compute_backoff_delay(retry_count)
        if delay <= 0:
            return
        if self._stop_event is not None:
            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            return
        await asyncio.sleep(delay)

    async def handle_webhook_notification(
        self,
        webhook_message: WebHookMessage,
        retry_count: int = 0,
        is_last_retry: bool = False,
    ) -> None:
        logger.info("Handling webhook notification")
        try:
            async with database_manager.local_session() as session:
                webhook_repo = WebHookRepository(session)
                event_repo = EventRepository(session)
                current_web_hook = await webhook_repo.get_by_id(
                    webhook_message.webhook_id
                )
                event_dto = await event_repo.get_last_event_by_execution_id(
                    webhook_message.workflow_execution_id
                )
        except (
            OperationalError,
            InterfaceError,
            SATimeoutError,
            DBAPIError,
            TimeoutError,
            ConnectionError,
            OSError,
        ) as db_exc:
            if (
                isinstance(db_exc, DBAPIError)
                and not isinstance(db_exc, (OperationalError, InterfaceError))
                and not db_exc.connection_invalidated
            ):
                logger.error(
                    "Non-retryable database error handling webhook notification: %s",
                    db_exc,
                )
                raise
            logger.warning(
                "Transient database error handling webhook notification (retry_count=%d): %s",
                retry_count,
                db_exc,
            )
            await self._sleep_before_retry(
                retry_count=retry_count, is_last_retry=is_last_retry
            )
            raise RetryableException(
                f"Transient database error handling webhook notification: {db_exc}"
            ) from db_exc

        if current_web_hook is None:
            err = EntityNotFoundException(
                entity_name="WebHook",
                entity_id=str(webhook_message.webhook_id),
            )
            logger.error("Error handling webhook notification: %s", err)
            raise err
        if event_dto is None:
            err = EntityNotFoundException(
                entity_name="Event",
                entity_id=str(webhook_message.workflow_execution_id),
            )
            logger.error("Error handling webhook notification: %s", err)
            raise err

        await self._deliver_webhook_with_retry_policy(
            current_web_hook,
            event_dto,
            retry_count=retry_count,
            is_last_retry=is_last_retry,
        )

    async def _deliver_webhook_with_retry_policy(
        self,
        webhook_dto: WebHookDTO,
        event_dto: EventDTO,
        *,
        retry_count: int = 0,
        is_last_retry: bool = False,
    ) -> None:
        try:
            await self._call_webhook_notification(webhook_dto, event_dto)
        except httpx.HTTPStatusError as http_exc:
            status_code = http_exc.response.status_code
            if self.should_retry_http_status(status_code):
                logger.warning(
                    "Retryable webhook HTTP status %d (retry_count=%d)",
                    status_code,
                    retry_count,
                )
                await self._sleep_before_retry(
                    retry_count=retry_count, is_last_retry=is_last_retry
                )
                raise RetryableException(
                    f"Webhook HTTP status {status_code}"
                ) from http_exc
            logger.error(
                "Non-retryable webhook HTTP status %d: %s",
                status_code,
                type(http_exc).__name__,
            )
            raise
        except httpx.TransportError as transport_exc:
            logger.warning(
                "Transient webhook transport error (retry_count=%d): %s",
                retry_count,
                type(transport_exc).__name__,
            )
            await self._sleep_before_retry(
                retry_count=retry_count, is_last_retry=is_last_retry
            )
            raise RetryableException(
                f"Webhook transport error: {type(transport_exc).__name__}"
            ) from transport_exc
        except Exception as exc:
            logger.error("Error handling webhook notification: %s", type(exc).__name__)
            raise

    @staticmethod
    def _build_headers(custom_headers: dict[str, str]) -> dict[str, str]:
        custom_content_type: str | None = None
        headers: dict[str, str] = {}
        for key, value in custom_headers.items():
            if key.lower() == "content-type":
                custom_content_type = value
            else:
                headers[key] = value
        headers["Content-Type"] = custom_content_type or "application/json"
        return headers

    async def _call_webhook_notification(
        self, webhook_dto: WebHookDTO, event_dto: EventDTO
    ) -> None:
        logger.info("Sending webhook notification")
        payload = self._execution_service.get_event_model(
            event_dto, event_dto.execution_id, is_debug_mode=False
        )
        headers = self._build_headers(webhook_dto.headers)

        client = self._get_http_client()
        response = await client.post(
            webhook_dto.url,
            content=payload.model_dump_json(),
            headers=headers,
        )
        response.raise_for_status()
        logger.info(
            "Webhook notification sent successfully with status %d",
            response.status_code,
        )


webhook_notification_service = WebhookNotificationService()
