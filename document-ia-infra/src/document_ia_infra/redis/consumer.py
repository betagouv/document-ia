"""
Classe Consumer commune pour les consumers Redis Stream
"""

import asyncio  # remplacement de threading+sleep
import contextlib
import functools
import logging
from asyncio import Task
from collections.abc import Callable
from document_ia_infra.redis.handler_execution import (
    HandlerExecution,
    run_handler_in_thread,
)
from document_ia_infra.redis.stream_delivery import StreamDelivery
from datetime import datetime, timezone
from typing import TypeVar, Generic, Optional, Any, Coroutine, cast

from redis.asyncio import Redis
from concurrent.futures import ThreadPoolExecutor

from document_ia_infra.redis.worker_error_policy import WorkerErrorPolicy
from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
    RedisManager,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 300000
IN_FLIGHT_SHUTDOWN_TIMEOUT_S = 10


class Consumer(Generic[T]):
    def __init__(
        self,
        consumer_name: str,
        consumer_group: str,
        stream_name: str,
        batch_size: int,
        block_time: int,
        message_class: type[T],
        process_message_callable: Callable[[T, int, bool], Coroutine[Any, Any, None]],
        worker_number: int = redis_settings.REDIS_WORKER_NUMBER,
        max_retry_number: int = 3,
        current_redis_manager: RedisManager = redis_manager_main_thread,
    ):
        # Borrowed manager: only its application/workflow owner closes it.
        self.redis_manager = current_redis_manager
        self.redis: Optional[Redis] = None
        self.reclaimer_task: Optional[Task[Any]] = None
        self.heartbeat_task: Optional[Task[Any]] = None
        self.stop_flag = asyncio.Event()
        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.message_class = message_class
        self.process_message_callable = process_message_callable
        # Battement d'inactivité : XAUTOCLAIM mesure l'inactivité depuis la
        # livraison, pas l'activité du handler. Ces ensembles suivent les
        # entrées en cours de traitement pour les rafraîchir.
        self._heartbeat_interval_s = max(RECLAIM_IDLE_MS / 3, 10) / 1000.0
        self._in_flight_ids: set[str] = set()
        self._reclaiming_ids: set[str] = set()
        self._processing_futures: set[asyncio.Future[Any]] = set()
        self._listener_done = asyncio.Event()
        self._draining = False

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.worker_number = worker_number
        self.max_retry_number = max_retry_number
        self.error_policy = WorkerErrorPolicy(max_retry_number)

        # DLQ stream
        self.dlq_stream_name = f"{self.stream_name}:dlq"

        self.delivery = StreamDelivery(stream_name, consumer_group, consumer_name)
        self.execution = HandlerExecution(worker_number, batch_size)

    @property
    def executor(self):
        return self.execution.executor

    @executor.setter
    def executor(self, executor: ThreadPoolExecutor):
        self.execution.executor = executor

    @property
    def has_running_handlers(self) -> bool:
        return any(not future.done() for future in self._processing_futures)

    async def start_consumer(self):
        logger.info(
            f"Start consumer {self.consumer_name} with {self.worker_number} workers"
        )
        logger.debug("Establishing connection to Redis...")

        try:
            await self._init_consumer()
            # Le battement est créé hors du TaskGroup : une annulation de
            # start_consumer() (par exemple à l'arrêt du worker sur signal)
            # annule le listener et le reclaimer, mais PAS le battement.
            # Celui-ci doit continuer de protéger les entrées tant que des
            # handlers tournent, et n'est arrêté qu'après la vidange (finally).
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_in_flight_entries(),
                name=f"heartbeat-{self.consumer_name}",
            )
            async with asyncio.TaskGroup() as tg:
                self.reclaimer_task = tg.create_task(
                    self._reclaim_pending_messages(),
                    name=f"reclaimer-{self.consumer_name}",
                )
                tg.create_task(
                    self._start_listening_messages(),
                    name=f"listener-{self.consumer_name}",
                )
        except (asyncio.CancelledError, Exception) as e:
            raise e
        finally:
            await self._shutdown_after_cancel()

    async def _shutdown_after_cancel(self):
        """Vidange les handlers puis arrête le battement, même sur annulation.

        Appelé dans le finally de start_consumer : que la sortie soit normale
        ou due à une annulation, on laisse la boucle principale finir sa
        vidange, on attend les handlers restants, et seulement ensuite on
        arrête le battement. Sans cela, une annulation tuerait le battement
        pendant que des handlers tournent encore.
        """
        self.stop_flag.set()
        # Keep the heartbeat alive during a bounded drain. The worker forces
        # process exit if a handler is still running after this deadline.
        try:
            await asyncio.wait_for(
                self._listener_done.wait(), timeout=IN_FLIGHT_SHUTDOWN_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for in-flight handlers to drain")
        except asyncio.CancelledError:
            pass
        # Arrêter le battement maintenant que les handlers sont vidangés.
        if self.heartbeat_task is not None and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._de_init_consumer()

    async def _init_consumer(self):
        try:
            self.redis = await self._get_safe_redis_connection()
            await self._ensure_consumer_group(self.redis)
            logger.info(f"✅ Consumer {self.consumer_name} initialized and ready")
        except ConnectionError as e:
            logger.error(f"❌ Error initializing consumer {self.consumer_name}: {e}")
            raise Exception(
                "Failed to initialize consumer due to Redis connection issues"
            ) from e

    async def _de_init_consumer(self):
        logger.info(f"Consumer {self.consumer_name} stopping...")
        if self.reclaimer_task and not self.reclaimer_task.done():
            self.reclaimer_task.cancel()
        self.execution.close()

    async def _start_listening_messages(self):
        self.redis = await self._get_safe_redis_connection()

        # On stocke les futures en cours EN DEHORS de la boucle while
        # Map: Future -> (msg_id, fields)
        active_futures: dict[asyncio.Future[Any], tuple[str, dict[str, Any]]] = {}

        try:
            loop = asyncio.get_running_loop()

            while not self.stop_flag.is_set():
                # 1. Nettoyage des tâches terminées (ACK/DLQ)
                # On vérifie s'il y a des tâches finies sans attendre
                # (Sauf si on est plein, voir plus bas)
                done_futures = [f for f in active_futures if f.done()]

                for fut in done_futures:
                    msg_id, fields = active_futures.pop(fut)
                    self._processing_futures.discard(fut)
                    self._in_flight_ids.discard(msg_id)
                    await self._handle_finished_future(fut, msg_id, fields, self.redis)

                # 2. Calcul de la capacité restante
                running_count = len(active_futures)
                free_slots = self.worker_number - running_count

                # 3. Stratégie de lecture
                if free_slots == 0:
                    # CAS A: On est PLEIN.
                    # On ne lit rien sur Redis. On attend obligatoirement qu'une tâche se finisse.
                    if active_futures:
                        stop_wait = asyncio.create_task(self.stop_flag.wait())
                        _, pending = await asyncio.wait(
                            {*active_futures.keys(), stop_wait},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop_wait in pending:
                            stop_wait.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await stop_wait
                    continue

                # CAS B: Il reste de la place.
                # On adapte le temps de blocage Redis.
                # Si on a des tâches en cours, on ne veut pas bloquer Redis trop longtemps
                # pour pouvoir ACK rapidement les tâches qui se terminent.
                current_block_time = 1000 if running_count > 0 else self.block_time

                try:
                    response = await self.delivery.read(
                        self.redis,
                        count=self.execution.read_capacity(running_count),
                        block=current_block_time,
                    )
                except Exception as e:
                    logger.error(f"Error reading stream: {e}")
                    await asyncio.sleep(1)
                    continue

                if not response:
                    continue

                _, entries = response[0]
                if not entries:
                    continue
                if self.stop_flag.is_set():
                    break

                # 4. Soumission des nouveaux messages.
                # Enregistrer TOUTES les entrées livrées avant le premier
                # await : une entrée en erreur de décodage peut bloquer sur
                # sa conservation DLQ, et les entrées suivantes du lot
                # resteraient non protégées contre une récupération.
                for msg_id, _fields in entries:
                    self._in_flight_ids.add(msg_id)
                for msg_id, fields in entries:
                    if self.stop_flag.is_set():
                        active_ids = {
                            active_id for active_id, _ in active_futures.values()
                        }
                        self._in_flight_ids.intersection_update(active_ids)
                        break
                    raw_data = fields.get("data")
                    retry_count = int(fields.get("retries", "0"))

                    try:
                        message_data: T = cast(
                            T, self.message_class.from_json(raw_data)
                        )
                    except Exception as decode_err:
                        logger.error(
                            "Message decode failed: %s", type(decode_err).__name__
                        )
                        if await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="decode_error",
                            error=type(decode_err).__name__,
                        ):
                            try:
                                await self.delivery.ack(self.redis, msg_id)
                            except Exception:
                                logger.error(f"ACK failed for decode_error {msg_id}")
                        # L'entrée est terminée (conservée ou laissée en
                        # attente pour une prochaine récupération) : cesser
                        # de la protéger pour ne pas la garder indéfiniment.
                        self._in_flight_ids.discard(msg_id)
                        continue

                    if self.stop_flag.is_set():
                        self._in_flight_ids.discard(msg_id)
                        continue

                    func = functools.partial(
                        self._process_message_sync_wrapper, message_data, retry_count
                    )

                    fut = loop.run_in_executor(self.executor, func)
                    active_futures[fut] = (msg_id, fields)
                    self._processing_futures.add(fut)

        except Exception as e:
            logger.error("Error in consumer loop shutdown: %s", type(e).__name__)
            self.stop_flag.set()
            raise e
        finally:
            # Attendre la fin des tâches restantes à l'arrêt si nécessaire
            if active_futures:
                logger.info(f"Waiting for {len(active_futures)} tasks to finish...")
                done, pending = await asyncio.wait(
                    active_futures.keys(), timeout=IN_FLIGHT_SHUTDOWN_TIMEOUT_S
                )
                # Traiter les futures terminées pour ACK/DLQ
                for fut in done:
                    msg_id, fields = active_futures.pop(fut, (None, None))  # type: ignore
                    if msg_id is not None and fields is not None:
                        self._processing_futures.discard(fut)
                        await self._handle_finished_future(
                            fut, msg_id, fields, self.redis
                        )
                if pending:
                    # Des handlers tournent encore : leurs entrées doivent
                    # rester protégées contre une récupération tant qu'ils
                    # ne sont pas terminés. On les suit dans une tâche de
                    # vidange qui ne lèvera la protection qu'à leur achèvement,
                    # au lieu de tout effacer maintenant (fenêtre de double
                    # livraison) ni de bloquer la boucle événement.
                    pending_ids = {
                        active_futures[f][0] for f in pending if f in active_futures
                    }
                    asyncio.create_task(self._drain_pending(pending, pending_ids))
                    # Ne pas marquer la vidange comme terminée ici : la tâche
                    # de vidange le fera. Le battement continue donc de
                    # protéger ces entrées pendant leur exécution.
                    self._draining = True
                    return
            # Signale au battement que la boucle principale est terminée :
            # celui-ci ne doit sortir qu'après la vidange complète du lot.
            self._listener_done.set()
            self._in_flight_ids.clear()

    async def _drain_pending(
        self, pending: set[asyncio.Future[Any]], pending_ids: set[str]
    ) -> None:
        """Achève les handlers restants puis lève la protection du battement."""
        try:
            if pending:
                await asyncio.wait(pending)
        except Exception:
            pass
        finally:
            self._in_flight_ids.difference_update(pending_ids)
            self._processing_futures.difference_update(pending)
            self._draining = False
            self._listener_done.set()

    async def _handle_finished_future(
        self,
        fut: asyncio.Future[Any],
        msg_id: str,
        fields: dict[str, Any],
        redis_connection: Redis,
    ) -> None:
        await self.error_policy.finish(
            fut,
            msg_id,
            fields,
            redis_connection,
            self.delivery,
            self._requeue_once,
            self._send_to_dlq,
        )

    def _process_message_sync_wrapper(self, message: T, retry_count: int) -> None:
        """Keep blocking workflow operations off the Redis/event-loop thread."""
        run_handler_in_thread(
            functools.partial(
                self.process_message_callable,
                message,
                retry_count,
                retry_count >= self.max_retry_number - 1,
            )
        )

    async def _ensure_consumer_group(self, redis_connection: Redis):
        await self.delivery.ensure_group(redis_connection, "$")

    async def _get_safe_redis_connection(self) -> Redis:
        self.redis = await self.redis_manager.get_connection()
        if self.redis is None:
            logger.error("❌ No Redis connection available, cannot start consumer")
            raise ConnectionError("No Redis connection available")
        return self.redis

    async def _requeue_once(
        self,
        redis_connection: Redis,
        msg_id: str,
        data: str,
        retries: int,
    ) -> bool:
        """Crée la copie de remise en file si absente, de façon atomique.

        Retourne True si la copie existe (créée par cet appel ou déjà
        présente), et laisse l'appelant acquitter l'original. Une exception
        remonte à l'appelant, qui laisse l'entrée en attente et retente à la
        passe suivante (échec fermé).

        Le script Lua rend la vérification et la copie atomiques : pas de
        réservation séparée à orpheliner (crash entre réserve et copie =
        perte de message), pas de doublon après une réponse perdue.
        """
        return await self.delivery.requeue(
            redis_connection, msg_id, {"data": data}, retries
        )

    async def _send_to_dlq(
        self,
        redis_connection: Redis,
        msg_id: str,
        fields: dict[str, Any],
        reason: str,
        error: Optional[str] = None,
    ) -> bool:
        """Conserve le message dans la DLQ de façon atomique et idempotente.

        Le script Lua recherche une entrée DLQ portant « original_id » et
        n'en crée une que si aucune n'existe. Conservation et dédup sont
        atomiques : pas de seconde ligne après un ACK en échec, pas de
        doublon entre rédacteurs DLQ concurrents, pas de résultat tronqué
        qui déclarerait « absent » une entrée présente plus loin.

        Retourne True si l'entrée est conservée (créée ou déjà présente) ;
        une exception est convertie en False pour que l'appelant laisse
        l'entrée en attente et retente à la passe suivante.
        """
        dlq_fields: dict[str, Any] = {
            "data": str(fields.get("data", "")),
            "retries": str(fields.get("retries", "0")),
            "original_id": str(msg_id),
            "reason": reason,
            "error": error or "",
            "failure_class": fields.get("failure_class", "internal"),
            "consumer": self.consumer_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            return await self.delivery.retain(redis_connection, msg_id, dlq_fields)
        except Exception as dlq_err:
            logger.error(
                f"Failed to retain message {msg_id} in DLQ "
                f"'{self.dlq_stream_name}': {type(dlq_err).__name__}; leaving entry pending"
            )
            return False

    # Récupère les messages en attente inactifs depuis plus de RECLAIM_IDLE_MS
    # et les remet en file pour traitement (xautoclaim puis xadd).
    # Convention partagée avec le chemin d'erreur du worker : le champ « retries »
    # compte les tentatives déjà consommées et max_retry_number est le nombre total
    # de tentatives autorisées. Une récupération consomme une seule tentative ;
    # une entrée épuisée est conservée dans la DLQ puis acquittée uniquement
    # après conservation confirmée.
    async def _reclaim_pending_messages(self):
        logger.info(f"Reclaimer task started idle_ms = {RECLAIM_IDLE_MS}")
        start = "0-0"

        self.redis = await self._get_safe_redis_connection()

        # Boucle continue jusqu'à stop_flag
        while not self.stop_flag.is_set():
            try:
                next_start, claimed, _ = await self.delivery.claim(
                    self.redis,
                    RECLAIM_IDLE_MS,
                    start,
                    count=1,
                )
                if self.stop_flag.is_set():
                    break
                claimed_ids = {msg_id for msg_id, _ in claimed}
                self._reclaiming_ids.update(claimed_ids)
                # Nettoyage par lot : une exception ou une annulation qui
                # interrompt le parcours ne doit laisser aucune entrée non
                # visitée protégée indéfiniment par le battement.
                try:
                    for msg_id, fields in claimed:
                        try:
                            await self._reclaim_entry(msg_id, fields)
                        finally:
                            self._reclaiming_ids.discard(msg_id)
                finally:
                    self._reclaiming_ids.difference_update(claimed_ids)
                start = next_start or "0-0"
                # Petit sleep coopératif
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error reclaiming pending messages: %s", type(e).__name__)
                await asyncio.sleep(5)
                continue
        logger.info("Reclaimer task stopped")

    async def _reclaim_entry(self, msg_id: str, fields: dict[str, Any]) -> None:
        """Retraite une entrée revendiquée : DLQ si épuisée, sinon remise en file."""
        logger.info("Reclaimed message ID: %s", msg_id)
        assert self.redis is not None
        try:
            attempts = int(fields.get("retries", "0")) + 1
        except (TypeError, ValueError):
            # Champ « retries » illisible : la tentative ne peut être comptée
            # ni la remise en file honorée. Conserver en DLQ plutôt que de
            # re-réclamer la même entrée indéfiniment.
            logger.error(
                f"Malformed retries field for reclaimed message {msg_id}. Moving to DLQ."
            )
            await self._retain_in_dlq_and_ack(
                msg_id,
                fields,
                "max_retries_exceeded",
                "Malformed retries field",
            )
            return
        if attempts >= self.max_retry_number:
            logger.error(
                f"Max attempts exceeded for reclaimed message {msg_id}. Moving to DLQ."
            )
            await self._retain_in_dlq_and_ack(
                msg_id,
                fields,
                "max_retries_exceeded",
                "Exceeded max retry count during reclaim",
            )
            return
        try:
            # Copie atomique et idempotente : créée si absente, retrouvée
            # sinon. L'acquittement n'a lieu que si la copie existe.
            await self._requeue_once(
                self.redis, msg_id, str(fields.get("data", "")), attempts
            )
            logger.info(f"Requeued reclaimed message {msg_id} (attempt {attempts})")
            try:
                await self.delivery.ack(self.redis, msg_id)
                logger.info(f"Acknowledged reclaimed message {msg_id}")
            except Exception:
                logger.error(f"ACK failed for reclaimed {msg_id}")
        except Exception as requeue_err:
            logger.error(
                "Failed to requeue reclaimed message %s: %s",
                msg_id,
                type(requeue_err).__name__,
            )

    async def _retain_in_dlq_and_ack(
        self, msg_id: str, fields: dict[str, Any], reason: str, error: str
    ) -> None:
        """Conserve l'entrée en DLQ puis l'acquitte après conservation confirmée."""
        assert self.redis is not None
        retained = await self._send_to_dlq(
            redis_connection=self.redis,
            msg_id=msg_id,
            fields=fields,
            reason=reason,
            error=error,
        )
        if not retained:
            logger.warning(
                f"Reclaimed message {msg_id} left pending: DLQ retention unconfirmed"
            )
            return
        try:
            await self.delivery.ack(self.redis, msg_id)
        except Exception:
            logger.error(f"ACK failed for reclaimed DLQ message {msg_id}")

    async def _heartbeat_in_flight_entries(self) -> None:
        """Rafraîchit l'inactivité des entrées en cours de traitement.

        XAUTOCLAIM mesure le temps depuis la livraison, pas l'activité du
        handler : un message sain dont le traitement dépasse RECLAIM_IDLE_MS
        serait revendiqué par le reclaimer de sa propre instance pendant son
        traitement, puis remis en file — livraison en double. Un battement
        XCLAIM (justid) remet le compteur d'inactivité à zéro toutes les
        RECLAIM_IDLE_MS / 3, marge de 3 au seuil de récupération. Les entrées
        acquittées ne sont plus dans la PEL et sont ignorées sans erreur.

        Le battement couvre le lot de la boucle principale et les entrées
        revendiquées en cours de retraitement. À l'arrêt, il ne sort que
        lorsque la boucle principale et le reclaimer sont terminés : une
        lecture bloquée peut encore livrer un lot après la demande d'arrêt,
        et sortir plus tôt exposerait ce lot à une récupération pendant
        l'arrêt gracieux.
        """
        logger.info(
            f"Heartbeat task started interval={self._heartbeat_interval_s:.3f}s"
        )
        while True:
            if self.stop_flag.is_set():
                # Ne sortir que lorsque les tâches qui peuvent remplir les
                # ensembles sont terminées. Des ensembles vides ne prouvent
                # rien — une lecture bloquée peut encore livrer après.
                listener_done = self._listener_done.is_set()
                reclaimer_done = (
                    self.reclaimer_task is None or self.reclaimer_task.done()
                )
                if listener_done and reclaimer_done:
                    break
                await asyncio.sleep(min(self._heartbeat_interval_s, 1.0))
            else:
                try:
                    await asyncio.wait_for(
                        self.stop_flag.wait(), timeout=self._heartbeat_interval_s
                    )
                except asyncio.TimeoutError:
                    pass
            ids = self._in_flight_ids | self._reclaiming_ids
            if not ids:
                continue
            try:
                if self.redis is not None:
                    await self.delivery.refresh(self.redis, ids)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
        logger.info("Heartbeat task stopped")
