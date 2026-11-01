import asyncio
import logging
import os
import socket
from typing import Any, Awaitable, Callable, Optional, TypeVar, Generic, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

import httpx

from document_ia_infra.redis.redis_manager import redis_manager
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

Handler = Callable[[T], Awaitable[None]]


def build_instance_consumer_name(base_name: str) -> str:
    """Nom de consommateur unique par instance de l'API.

    En mode groupé, chaque instance doit posséder une identité de consommateur
    distincte et observable (XINFO CONSUMERS) : les entrées livrées mais non
    acquittées restent dans la PEL du consommateur qui les a lues, et la
    récupération par XAUTOCLAIM suppose de pouvoir distinguer les instances.
    """
    return f"{base_name}-{socket.gethostname()}-{os.getpid()}"


class SimpleStreamConsumer(Generic[T]):
    """Consumer Redis Stream minimaliste.

    Deux modes:
    - XREAD (non groupé) si aucun consumer_group/consumer_name n'est fourni
    - XREADGROUP (groupé) si consumer_group et consumer_name sont fournis

    Dans le mode groupé, le consumer ack les messages après exécution du handler
    et crée automatiquement le groupe si nécessaire (mkstream=True).

    En mode groupé avec auto_ack, une tâche de récupération reclame les entrées
    livrées mais jamais acquittées (instance arrêtée ou plantée) via XAUTOCLAIM,
    puis les remet en file ; les entrées épuisées sont conservées en DLQ puis
    acquittées après conservation confirmée.

    La remise en file est idempotente : une copie déjà créée puis un ACK en
    échec ne produit jamais de deuxième copie, et une erreur de parcours de
    garde laisse l'entrée en attente plutôt que d'en créer une deuxième. Les
    entrées en cours de traitement (lot de la boucle principale ou travail de
    la récupération) sont protégées par un battement qui rafraîchit leur
    inactivité, y compris pendant la vidange du lot à l'arrêt.
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
        reclaim_idle_ms: int = 300_000,
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
        self._reclaim_idle_ms = reclaim_idle_ms
        self._redis: Optional[Redis] = None
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task[Any]] = None
        self._reclaimer_task: Optional[asyncio.Task[Any]] = None
        self._heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._heartbeat_interval_s = max(reclaim_idle_ms / 3, 10) / 1000.0
        self._batch_ids: set[Any] = set()
        self._reclaiming_ids: set[Any] = set()
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
        if self._group and self._consumer and self._auto_ack:
            self._reclaimer_task = asyncio.create_task(
                self._reclaim_pending_messages(),
                name=f"simple-consumer-reclaimer:{self._stream}",
            )
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_in_flight_entries(),
                name=f"simple-consumer-heartbeat:{self._stream}",
            )
        logger.info(
            "SimpleStreamConsumer started (stream='%s', mode=%s, reclaimer=%s)",
            self._stream,
            "group" if (self._group and self._consumer) else "simple",
            self._reclaimer_task is not None,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        for task in (self._task, self._reclaimer_task, self._heartbeat_task):
            if task is None:
                continue
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for SimpleStreamConsumer task to stop")
            except Exception as e:
                logger.error("Error stopping SimpleStreamConsumer task: %s", e)

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
                id=self._last_id,
                mkstream=True,
            )
            logger.info(
                "Created consumer group '%s' on stream '%s' (start id=%s)",
                self._group,
                self._stream,
                self._last_id,
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
    ) -> bool:
        dlq_stream = f"{stream_name}:dlq"
        payload = fields.get("data")
        try:
            already_retained = await self._already_retained_in_dlq(
                redis, stream_name, entry_id
            )
        except Exception as scan_err:
            # Échec du parcours d'idempotence : l'état de conservation est
            # inconnu, pas « absent ». Ni écrire une seconde copie, ni
            # laisser l'appelant acquitter — l'entrée reste en attente et
            # la passe suivante réessaie.
            logger.error(
                "Unable to confirm DLQ retention for message %s in '%s': %s; "
                "leaving entry pending",
                entry_id,
                dlq_stream,
                scan_err,
            )
            return False
        if already_retained:
            logger.info(
                "Message %s already retained in DLQ '%s'; skipping duplicate write",
                entry_id,
                dlq_stream,
            )
            return True
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
            return True
        except Exception as dlq_err:
            logger.error(
                "Unable to push message %s to DLQ '%s': %s",
                entry_id,
                dlq_stream,
                dlq_err,
            )
            return False

    async def _already_retained_in_dlq(
        self,
        redis: Redis,
        stream_name: str,
        entry_id: Any,
    ) -> bool:
        """Vérifie si l'entrée d'origine est déjà conservée dans la DLQ.

        Une conservation DLQ réussie suivie d'un ACK en échec laisse l'entrée
        d'origine en attente : une nouvelle récupération ne doit pas la
        conserver une deuxième fois. L'entrée DLQ d'un message ne peut exister
        qu'à partir de sa milliseconde de création ; les numéros de séquence
        sont indépendants par flux, le parcours couvre donc toute la
        milliseconde d'origine et ignore l'historique antérieur de la DLQ.

        Échec fermé : une erreur de parcours remonte à l'appelant, qui
        laisse l'entrée en attente et retente à la passe suivante — ne
        jamais conclure « pas conservée » sur un parcours incertain.
        """
        dlq_stream = f"{stream_name}:dlq"
        source_ms = str(entry_id).split("-")[0]
        entries = await redis.xrange(dlq_stream, min=f"{source_ms}-0")
        for _entry_id, entry_fields in entries:
            if str(entry_fields.get("original_id", "")) == str(entry_id):
                return True
        return False

    async def _handle_message_with_retry(
        self,
        redis: Redis,
        stream_name: str,
        entry_id: Any,
        fields: dict[str, Any],
        message_data: T,
    ) -> bool:
        attempt = 0
        while True:
            try:
                await self._handler(message_data)
                return True
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if not self._should_retry_http(status):
                    logger.warning(
                        "HTTP %s is not retryable for stream=%s id=%s",
                        status,
                        stream_name,
                        entry_id,
                    )
                    return await self._send_to_dlq(
                        redis,
                        stream_name,
                        entry_id,
                        fields,
                        f"Non retryable HTTP {status}",
                    )
                if attempt >= self._max_retries:
                    return await self._send_to_dlq(
                        redis,
                        stream_name,
                        entry_id,
                        fields,
                        f"Max retries exceeded (HTTP {status})",
                    )
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

                if self._group and self._consumer:
                    self._batch_ids = {
                        entry_id for _, entries in response for entry_id, _ in entries
                    }
                try:
                    for stream_name, entries in response:
                        for entry_id, fields in entries:
                            should_ack = False
                            try:
                                message_data: T = cast(
                                    T, self._message_class.from_json(fields["data"])
                                )

                                should_ack = await self._handle_message_with_retry(
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
                                if (
                                    should_ack
                                    and self._group
                                    and self._consumer
                                    and self._auto_ack
                                ):
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
                                    if not (self._group and self._consumer):
                                        # Avance le curseur uniquement en mode simple
                                        self._last_id = entry_id
                finally:
                    self._batch_ids = set()

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

    async def _heartbeat_in_flight_entries(self) -> None:
        """Rafraîchit l'inactivité des entrées en cours de traitement.

        XAUTOCLAIM mesure le temps depuis la livraison, pas l'activité du
        handler : un lot sain traité séquentiellement (jusqu'à `count`
        entrées) deviendrait éligible à la récupération pendant son propre
        traitement. Un battement XCLAIM (justid) remet le compteur
        d'inactivité à zéro toutes les `reclaim_idle_ms / 3`, laissant une
        marge de 3 au seuil de récupération. Les entrées acquittées ne sont
        plus dans la PEL et sont ignorées par XCLAIM sans erreur.

        Le battement couvre à la fois le lot de la boucle principale et les
        entrées revendiquées par la récupération en cours de retraitement.
        À l'arrêt, il ne sort que lorsque les tâches de travail sont
        terminées : une lecture bloquée peut encore livrer un lot après la
        demande d'arrêt, et sortir plus tôt — sur la seule vacuité des
        ensembles — exposerait ce lot à une récupération par une autre
        instance pendant l'arrêt gracieux.
        """
        logger.info(
            "Heartbeat task started (stream='%s', interval=%.3fs)",
            self._stream,
            self._heartbeat_interval_s,
        )
        while True:
            if self._stop_event.is_set():
                # Arrêt demandé : ne sortir que lorsque les tâches qui
                # peuvent remplir les ensembles sont terminées. Des
                # ensembles vides ne prouvent rien — une lecture bloquée
                # peut encore livrer un lot après la demande d'arrêt.
                if self._worker_tasks_done():
                    break
                # Cadence bornée pendant la vidange pour rester réactif.
                await asyncio.sleep(min(self._heartbeat_interval_s, 1.0))
            else:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._heartbeat_interval_s
                    )
                except asyncio.TimeoutError:
                    pass
            ids = self._batch_ids | self._reclaiming_ids
            if not ids:
                continue
            try:
                redis = await self._ensure_connection()
                if redis is None:
                    continue
                await redis.xclaim(
                    self._stream,
                    self._group or "",
                    self._consumer or "",
                    min_idle_time=0,
                    message_ids=list(ids),
                    justid=True,
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Heartbeat failed for stream=%s: %s", self._stream, e)
        logger.info("Heartbeat task stopped (stream='%s')", self._stream)

    def _worker_tasks_done(self) -> bool:
        """Les tâches susceptibles de remplir les ensembles sont-elles finies ?"""
        run_done = self._task is None or self._task.done()
        reclaim_done = self._reclaimer_task is None or self._reclaimer_task.done()
        return run_done and reclaim_done

    async def _reclaim_pending_messages(self) -> None:
        """Récupère les entrées livrées mais jamais acquittées (XAUTOCLAIM).

        Une instance arrêtée ou plantée entre la lecture et l'ACK laisse ses
        entrées en attente dans la PEL du groupe. Après `reclaim_idle_ms` sans
        activité, ces entrées sont reclaims puis remises en file pour être
        relivées ; les entrées épuisées sont conservées en DLQ puis acquittées
        uniquement après conservation confirmée. Les entrées actives — lot de
        la boucle principale ou entrées revendiquées en cours de retraitement
        — restent protégées par le battement d'inactivité, qui maintient leur
        compteur en dessous du seuil.

        Convention partagée avec le worker : le champ « retries » compte les
        tentatives déjà consommées et max_retries est le nombre total de
        tentatives autorisées. Une récupération consomme une seule tentative.
        Un champ « retries » illisible ne peut ni être compté ni remis en
        file : l'entrée est conservée en DLQ plutôt que re-réclamée à
        chaque passe.
        """
        logger.info(
            "Reclaimer task started (stream='%s', group='%s', idle_ms=%d)",
            self._stream,
            self._group,
            self._reclaim_idle_ms,
        )
        start = "0-0"
        while not self._stop_event.is_set():
            try:
                redis = await self._ensure_connection()
                if redis is None:
                    await asyncio.sleep(2)
                    continue

                next_start, claimed, _ = await redis.xautoclaim(
                    self._stream,
                    self._group,
                    self._consumer,
                    self._reclaim_idle_ms,
                    start,
                    count=self._count,
                )
                claimed_ids = {entry_id for entry_id, _ in claimed}
                self._reclaiming_ids.update(claimed_ids)
                # Nettoyage par lot : une exception ou une annulation qui
                # interrompt le parcours ne doit laisser aucune entrée non
                # visitée protégée indéfiniment par le battement.
                try:
                    for entry_id, fields in claimed:
                        try:
                            await self._reclaim_entry(redis, entry_id, fields)
                        finally:
                            self._reclaiming_ids.discard(entry_id)
                finally:
                    self._reclaiming_ids.difference_update(claimed_ids)
                start = next_start or "0-0"
                # Petit sleep coopératif
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Reclaimer loop error for stream=%s: %s", self._stream, e)
                await asyncio.sleep(5)
        logger.info("Reclaimer task stopped (stream='%s')", self._stream)

    async def _reclaim_entry(
        self,
        redis: Redis,
        entry_id: Any,
        fields: dict[str, Any],
    ) -> None:
        try:
            attempts = int(fields.get("retries", "0")) + 1
        except (TypeError, ValueError):
            # Champ « retries » illisible : la tentative ne peut être
            # comptée ni la remise en file honorée. Conserver en DLQ plutôt
            # que de re-réclamer la même entrée indéfiniment.
            logger.error(
                "Malformed retries field for reclaimed entry stream=%s id=%s: "
                "%r. Moving to DLQ.",
                self._stream,
                entry_id,
                fields.get("retries"),
            )
            await self._retain_in_dlq_and_ack(
                redis,
                entry_id,
                fields,
                f"Malformed retries field: {fields.get('retries')!r}",
            )
            return
        if attempts >= self._max_retries:
            logger.error(
                "Max retries exceeded for reclaimed entry stream=%s id=%s "
                "(attempt %d/%d). Moving to DLQ.",
                self._stream,
                entry_id,
                attempts,
                self._max_retries,
            )
            await self._retain_in_dlq_and_ack(
                redis,
                entry_id,
                fields,
                f"Max retries exceeded during reclaim ({attempts}/{self._max_retries})",
            )
            return
        try:
            if await self._already_requeued(redis, entry_id):
                logger.info(
                    "Reclaimed entry stream=%s id=%s already requeued; "
                    "retrying ACK only",
                    self._stream,
                    entry_id,
                )
            else:
                fields["retries"] = str(attempts)
                fields["original_id"] = str(entry_id)
                await redis.xadd(self._stream, fields)
                logger.info(
                    "Requeued reclaimed entry stream=%s id=%s (attempt %d/%d)",
                    self._stream,
                    entry_id,
                    attempts,
                    self._max_retries,
                )
            try:
                await redis.xack(self._stream, self._group, entry_id)
                logger.info(
                    "Acknowledged reclaimed entry stream=%s id=%s",
                    self._stream,
                    entry_id,
                )
            except Exception as ack_err:
                logger.error(
                    "ACK failed for reclaimed entry stream=%s id=%s: %s",
                    self._stream,
                    entry_id,
                    ack_err,
                )
        except Exception as requeue_err:
            logger.error(
                "Failed to requeue reclaimed entry stream=%s id=%s: %s",
                self._stream,
                entry_id,
                requeue_err,
            )

    async def _retain_in_dlq_and_ack(
        self,
        redis: Redis,
        entry_id: Any,
        fields: dict[str, Any],
        error_message: str,
    ) -> None:
        """Conserve l'entrée en DLQ puis l'acquitte après conservation confirmée."""
        retained = await self._send_to_dlq(
            redis, self._stream, entry_id, fields, error_message
        )
        if not retained:
            logger.warning(
                "Reclaimed entry stream=%s id=%s left pending: DLQ retention unconfirmed",
                self._stream,
                entry_id,
            )
            return
        try:
            await redis.xack(self._stream, self._group, entry_id)
        except Exception as ack_err:
            logger.error(
                "ACK failed for reclaimed DLQ entry stream=%s id=%s: %s",
                self._stream,
                entry_id,
                ack_err,
            )

    async def _already_requeued(
        self,
        redis: Redis,
        entry_id: Any,
    ) -> bool:
        """Vérifie si l'entrée d'origine est déjà remise en file par récupération.

        Une remise en file réussie suivie d'un ACK en échec laisse l'entrée
        d'origine en attente : une nouvelle récupération ne doit pas créer une
        deuxième copie. Les copies portent le champ « original_id » et ne
        peuvent exister qu'après l'entrée d'origine dans le même flux.

        Échec fermé : une erreur de parcours remonte à l'appelant, qui
        laisse l'entrée en attente et retente à la passe suivante — ne
        jamais conclure « pas de copie » sur un parcours incertain.
        """
        entries = await redis.xrange(self._stream, min=str(entry_id))
        for _entry_id, entry_fields in entries:
            if str(entry_fields.get("original_id", "")) == str(entry_id):
                return True
        return False
