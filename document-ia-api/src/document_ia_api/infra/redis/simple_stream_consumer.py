import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar, Generic, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

import httpx

from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

Handler = Callable[[T], Awaitable[None]]


class SimpleStreamConsumer(Generic[T]):
    """Consumer Redis Stream minimaliste.

    Deux modes:
    - XREAD (non groupé) si aucun consumer_group/consumer_name n'est fourni
    - XREADGROUP (groupé) si consumer_group et consumer_name sont fournis

    Dans le mode groupé, le consumer ack les messages après exécution du handler
    et crée automatiquement le groupe si nécessaire (mkstream=True).
    """

    def __init__(
        self,
        *,
        stream_name: str,
        handler: Handler[T],
        message_class: type[T],
        start_from: str = "0-0",  # "$" => seulement nouveaux messages, "0-0" pour tout l'historique
        consumer_group: Optional[str] = None,
        consumer_name: Optional[str] = None,
        auto_ack: bool = True,
        # Paramètres communs
        block_ms: int = 5000,
        count: int = 50,
        max_retries: int = 3,
        retry_initial_delay_seconds: float = 5.0,
        retry_backoff_multiplier: float = 2.0,
    ) -> None:
        self._stream = stream_name
        self._handler = handler
        self._message_class = message_class
        self._last_id = start_from
        self._block_ms = block_ms
        self._count = count
        self._redis: Optional[Redis] = None
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task[Any]] = None
        # Group mode
        self._group = consumer_group
        self._consumer = consumer_name
        self._auto_ack = auto_ack
        self._max_retries = max_retries
        self._retry_initial_delay_seconds = retry_initial_delay_seconds
        self._retry_backoff_multiplier = retry_backoff_multiplier

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        # En mode groupé, s'assurer de l'existence du groupe (création si besoin)
        if self._group and self._consumer:
            await self._ensure_group()
        self._task = asyncio.create_task(
            self._run(), name=f"simple-consumer:{self._stream}"
        )
        logger.info(
            "SimpleStreamConsumer started (stream='%s', mode=%s)",
            self._stream,
            "group" if (self._group and self._consumer) else "simple",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for SimpleStreamConsumer to stop")
            except Exception as e:
                logger.error("Error stopping SimpleStreamConsumer: %s", e)

    async def _ensure_connection(self) -> Optional[Redis]:
        if self._redis is not None:
            return self._redis
        self._redis = await redis_manager.get_connection()
        if self._redis is None:
            logger.error("SimpleStreamConsumer: no Redis connection available")
        return self._redis

    async def _ensure_group(self) -> None:
        redis = await self._ensure_connection()
        if redis is None:
            return
        try:
            await redis.xgroup_create(
                name=self._stream,
                groupname=self._group or "",
                id="0-0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group '%s' on stream '%s' (start id=%s)",
                self._group,
                self._stream,
                "0-0",
            )
        except ResponseError as e:
            # Groupe déjà existant => ok
            if "BUSYGROUP" in str(e):
                logger.info(
                    "Consumer group '%s' already exists on stream '%s'",
                    self._group,
                    self._stream,
                )
            else:
                raise

    def _should_retry_http(self, status_code: int) -> bool:
        if status_code in {400, 401, 403, 422}:
            return False
        return 400 <= status_code < 600

    def _compute_backoff_delay(self, attempt: int) -> float:
        return self._retry_initial_delay_seconds * (
            self._retry_backoff_multiplier**attempt
        )

    async def _send_to_dlq(
        self,
        redis: Redis,
        stream_name: str,
        entry_id: Any,
        fields: dict[str, Any],
        error_message: str,
    ) -> None:
        dlq_stream = f"{stream_name}:dlq"
        payload = fields.get("data")
        try:
            await redis.xadd(
                dlq_stream,
                {
                    "original_stream": stream_name,
                    "original_id": str(entry_id),
                    "error": error_message,
                    "data": payload or "",
                },
            )
            logger.warning(
                "Message %s moved to DLQ '%s' due to: %s",
                entry_id,
                dlq_stream,
                error_message,
            )
        except Exception as dlq_err:
            logger.error(
                "Unable to push message %s to DLQ '%s': %s",
                entry_id,
                dlq_stream,
                dlq_err,
            )

    async def _handle_message_with_retry(
        self,
        redis: Redis,
        stream_name: str,
        entry_id: Any,
        fields: dict[str, Any],
        message_data: T,
    ) -> None:
        attempt = 0
        while True:
            try:
                await self._handler(message_data)
                return
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if not self._should_retry_http(status):
                    logger.warning(
                        "HTTP %s is not retryable for stream=%s id=%s",
                        status,
                        stream_name,
                        entry_id,
                    )
                    await self._send_to_dlq(
                        redis,
                        stream_name,
                        entry_id,
                        fields,
                        f"Non retryable HTTP {status}",
                    )
                    return
                if attempt >= self._max_retries:
                    await self._send_to_dlq(
                        redis,
                        stream_name,
                        entry_id,
                        fields,
                        f"Max retries exceeded (HTTP {status})",
                    )
                    return
                delay = self._compute_backoff_delay(attempt)
                attempt += 1
                logger.warning(
                    "HTTP error %s on stream=%s id=%s (attempt %d/%d). Retry in %.1fs",
                    status,
                    stream_name,
                    entry_id,
                    attempt,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                redis = await self._ensure_connection()
                if redis is None:
                    await asyncio.sleep(2)
                    continue

                if self._group and self._consumer:
                    # Mode groupé: lire et ack
                    response = await redis.xreadgroup(
                        groupname=self._group,
                        consumername=self._consumer,
                        streams={self._stream: ">"},
                        count=self._count,
                        block=self._block_ms,
                    )
                else:
                    # Mode simple: XREAD
                    response = await redis.xread(
                        streams={self._stream: self._last_id},
                        block=self._block_ms,
                        count=self._count,
                    )

                if not response:
                    continue

                for stream_name, entries in response:
                    for entry_id, fields in entries:
                        try:
                            message_data: T = cast(
                                T, self._message_class.from_json(fields["data"])
                            )

                            await self._handle_message_with_retry(
                                redis,
                                stream_name,
                                entry_id,
                                fields,
                                message_data,
                            )
                        except Exception as h_err:
                            logger.error(
                                "Handler error for stream=%s id=%s: %s",
                                stream_name,
                                entry_id,
                                h_err,
                            )
                        finally:
                            if self._group and self._consumer and self._auto_ack:
                                try:
                                    await redis.xack(
                                        self._stream, self._group, entry_id
                                    )
                                except Exception as ack_err:
                                    logger.error(
                                        "ACK error for stream=%s id=%s: %s",
                                        stream_name,
                                        entry_id,
                                        ack_err,
                                    )
                            else:
                                # Avance le curseur uniquement en mode simple
                                self._last_id = entry_id

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SimpleStreamConsumer loop error: %s", e)
                await asyncio.sleep(1)
        logger.info(
            "SimpleStreamConsumer loop stopped (stream='%s', mode=%s)",
            self._stream,
            "group" if (self._group and self._consumer) else "simple",
        )
