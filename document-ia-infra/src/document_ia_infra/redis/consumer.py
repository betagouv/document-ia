"""
Classe Consumer commune pour les consumers Redis Stream
"""

import asyncio  # remplacement de threading+sleep
import functools
import logging
import gc
from asyncio import Task
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TypeVar, Generic, Optional, Any, Coroutine, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.typing import FieldT, EncodableT

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.redis_manager import (
    redis_manager as redis_manager_main_thread,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.redis.serializable_message import SerializableMessage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SerializableMessage)

RECLAIM_IDLE_MS = 300000
DLQ_SCAN_BATCH_SIZE = 200


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
    ):
        if max_retry_number < 1:
            raise ValueError("max_retry_number must be >= 1")
        self.redis: Optional[Redis] = None
        self.reclaimer_task: Optional[Task[Any]] = None
        self.stop_flag = asyncio.Event()
        self.consumer_name = consumer_name
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.message_class = message_class
        self.process_message_callable = process_message_callable

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time  # en ms pour xreadgroup
        self.worker_number = worker_number
        self.max_retry_number = max_retry_number

        # DLQ stream
        self.dlq_stream_name = f"{self.stream_name}:dlq"

        self.executor = ThreadPoolExecutor(max_workers=self.worker_number)

    async def start_consumer(self):
        logger.info(
            f"Start consumer {self.consumer_name} with {self.worker_number} workers"
        )
        logger.debug("Establishing connection to Redis...")

        try:
            await self._init_consumer()
            async with asyncio.TaskGroup() as tg:
                self.reclaimer_task = tg.create_task(
                    self._reclaim_pending_messages(),
                    name=f"reclaimer-{self.consumer_name}",
                )
                tg.create_task(
                    self._start_listening_messages(),
                    name=f"listener-{self.consumer_name}",
                )
        except Exception as e:
            raise e
        finally:
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
        if self.reclaimer_task:
            try:
                await asyncio.wait_for(self.reclaimer_task, timeout=10)
            except Exception:
                pass
        self.executor.shutdown(wait=True)
        await redis_manager_main_thread.close()

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
                    await self._handle_finished_future(fut, msg_id, fields, self.redis)

                # 2. Calcul de la capacité restante
                running_count = len(active_futures)
                free_slots = self.worker_number - running_count

                # 3. Stratégie de lecture
                if free_slots == 0:
                    # CAS A: On est PLEIN.
                    # On ne lit rien sur Redis. On attend obligatoirement qu'une tâche se finisse.
                    if active_futures:
                        _, _ = await asyncio.wait(
                            active_futures.keys(), return_when=asyncio.FIRST_COMPLETED
                        )
                    continue

                # CAS B: Il reste de la place.
                # On adapte le temps de blocage Redis.
                # Si on a des tâches en cours, on ne veut pas bloquer Redis trop longtemps
                # pour pouvoir ACK rapidement les tâches qui se terminent.
                current_block_time = 1000 if running_count > 0 else self.block_time

                try:
                    response = await self.redis.xreadgroup(
                        self.consumer_group,
                        self.consumer_name,
                        streams={self.stream_name: ">"},
                        count=free_slots,
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

                # 4. Soumission des nouveaux messages
                for msg_id, fields in entries:
                    raw_data = fields.get("data")

                    try:
                        retry_count = self._parse_retry_count(fields)
                        message_data: T = cast(
                            T, self.message_class.from_json(raw_data)
                        )
                    except Exception as decode_err:
                        logger.error(f"Erreur décodage message {msg_id}: {decode_err}")
                        if await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="decode_error",
                            error=str(decode_err),
                        ):
                            try:
                                await self.redis.xack(
                                    self.stream_name, self.consumer_group, msg_id
                                )
                            except Exception:
                                logger.error(f"ACK failed for decode_error {msg_id}")
                        continue

                    func = functools.partial(
                        self._process_message_sync_wrapper, message_data, retry_count
                    )

                    fut = loop.run_in_executor(self.executor, func)
                    active_futures[fut] = (msg_id, fields)

        except Exception as e:
            logger.error(f"Error in consumer loop shutdown: {e}")
            self.stop_flag.set()
            raise e
        finally:
            # Attendre la fin des tâches restantes à l'arrêt si nécessaire
            if active_futures:
                logger.info(f"Waiting for {len(active_futures)} tasks to finish...")
                done, _ = await asyncio.wait(active_futures.keys(), timeout=10)
                # Traiter les futures terminées pour ACK/DLQ
                for fut in done:
                    msg_id, fields = active_futures.pop(fut, (None, None))  # type: ignore
                    if msg_id is not None and fields is not None:
                        await self._handle_finished_future(
                            fut, msg_id, fields, self.redis
                        )

    async def _handle_finished_future(
        self,
        fut: asyncio.Future[Any],
        msg_id: str,
        fields: dict[str, Any],
        redis_connection: Redis,
    ) -> None:
        """Gestionnaire de résultat extrait de la boucle principale pour lisibilité"""
        try:
            fut.result()
            # Succès
            try:
                await redis_connection.xack(
                    self.stream_name, self.consumer_group, msg_id
                )
            except Exception:
                # Ne pas crash si ACK échoue
                logger.error(f"ACK failed for success {msg_id}")

        except RetryableException as retry_exc:
            logger.warning(f"Retryable failure for {msg_id}: {retry_exc}")
            try:
                retry_count = self._parse_retry_count(fields)
            except Exception as parse_err:
                logger.error(
                    f"Invalid retries metadata for message {msg_id}: {parse_err}"
                )
                if await self._send_to_dlq(
                    redis_connection,
                    msg_id,
                    fields,
                    "decode_error",
                    str(parse_err),
                ):
                    try:
                        await redis_connection.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                    except Exception:
                        logger.error(f"ACK failed for decode_error {msg_id}")
                return
            data = fields.get("data", "")

            if retry_count < self.max_retry_number - 1:
                try:
                    await redis_connection.xadd(
                        self.stream_name,
                        {"data": data, "retries": str(retry_count + 1)},
                    )
                    try:
                        await redis_connection.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                    except Exception:
                        logger.error(f"ACK failed after requeue {msg_id}")
                except Exception as requeue_err:
                    logger.error(f"Requeue failed {msg_id}: {requeue_err}")
                    if await self._send_to_dlq(
                        redis_connection,
                        msg_id,
                        fields,
                        "error_requeueing_message",
                        str(requeue_err),
                    ):
                        try:
                            await redis_connection.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                        except Exception:
                            logger.error(f"ACK failed after requeue failure {msg_id}")
            else:
                logger.error(f"Max retries exceeded {msg_id}")
                if await self._send_to_dlq(
                    redis_connection,
                    msg_id,
                    fields,
                    "max_retries_exceeded",
                    str(retry_exc),
                ):
                    try:
                        await redis_connection.xack(
                            self.stream_name, self.consumer_group, msg_id
                        )
                    except Exception:
                        logger.error(f"ACK failed for max_retries_exceeded {msg_id}")

        except Exception as proc_err:
            logger.error(f"Fatal error message {msg_id}: {proc_err}")
            if await self._send_to_dlq(
                redis_connection, msg_id, fields, "not_retryable_error", str(proc_err)
            ):
                try:
                    await redis_connection.xack(
                        self.stream_name, self.consumer_group, msg_id
                    )
                except Exception:
                    logger.error(f"ACK failed for not_retryable_error {msg_id}")

    def _process_message_sync_wrapper(self, message: T, retry_count: int) -> None:
        """Fonction exécutée dans un thread.
        Crée un nouvel event loop pour exécuter la coroutine process_message_callable.
        ATTENTION : si process_message_callable accède à des objets liés à l'évent loop principal
        (ex : connexion Redis asynchrone déjà créée), cela peut poser un problème. Dans ce cas, il
        faudrait refactorer pour ne déplacer dans le thread que la partie CPU-bound.
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.process_message_callable(
                    message, retry_count, retry_count >= self.max_retry_number - 1
                )
            )
        finally:
            try:
                # 1. Déclencher la garbage collection pour appeler les destructeurs __del__ des objets non fermés
                # (comme les clients HTTPX/OpenAI créés dans ce thread) et enregistrer leurs tâches de fermeture.
                gc.collect()

                # 2. Récupérer toutes les tâches restantes (y compris les aclose() créés par la GC)
                # et les laisser s'exécuter jusqu'à la fin avant de fermer la boucle.
                pending_tasks = asyncio.all_tasks(loop)
                if pending_tasks:
                    try:
                        loop.run_until_complete(
                            asyncio.wait_for(
                                asyncio.gather(*pending_tasks, return_exceptions=True),
                                timeout=5.0,
                            )
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Timeout waiting for pending tasks to finish during thread loop shutdown"
                        )
                    except Exception as shutdown_err:
                        logger.error(
                            f"Error executing pending tasks during thread loop shutdown: {shutdown_err}"
                        )

                # 3. Arrêter les générateurs asynchrones
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as e:
                logger.error(f"Error during thread loop cleanup: {e}")
                pass
            finally:
                loop.close()

    async def _ensure_consumer_group(self, redis_connection: Redis):
        try:
            await redis_connection.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id="$",
                mkstream=True,
            )
            logger.info(
                f"Consumer group created stream = {self.stream_name}, group= {self.consumer_group}"
            )
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(
                    f"Consumer group already exists, group = {self.consumer_group}"
                )
            else:
                raise

    async def _get_safe_redis_connection(self) -> Redis:
        self.redis = await redis_manager_main_thread.get_connection()
        if self.redis is None:
            logger.error("❌ No Redis connection available, cannot start consumer")
            raise ConnectionError("No Redis connection available")
        return self.redis

    @staticmethod
    def _parse_retry_count(fields: dict[str, Any]) -> int:
        if "retries" not in fields:
            return 0
        raw_retries = fields["retries"]
        if isinstance(raw_retries, bool) or raw_retries is None:
            raise ValueError(f"Invalid retries value: {raw_retries!r}")
        retry_count = int(raw_retries)
        if retry_count < 0:
            raise ValueError(f"Negative retries value: {retry_count}")
        return retry_count

    @staticmethod
    def _dlq_scan_start_id(msg_id: str) -> str:
        source_ms, sep, _seq = msg_id.partition("-")
        if sep and source_ms.isdigit():
            return f"{source_ms}-0"
        return "-"

    async def _already_retained_in_dlq(
        self, redis_connection: Redis, msg_id: str
    ) -> bool:
        """Vérifie si le message d'origine est déjà conservé dans la DLQ.

        Une conservation DLQ réussie suivie d'un ACK en échec laisse l'entrée
        d'origine en attente : une nouvelle récupération ne doit pas la
        conserver une deuxième fois. L'entrée DLQ d'un message ne peut exister
        qu'à partir de sa milliseconde de création ; les numéros de séquence
        sont indépendants par flux, le parcours démarre donc à <source_ms>-0
        par lots bornés et ignore l'historique antérieur de la DLQ.

        Lève toute erreur Redis afin que les appelants échouent en mode fermé
        (pas d'écriture DLQ en doublon ni d'ACK prématuré si la lecture échoue).
        """
        cursor = self._dlq_scan_start_id(msg_id)
        target_id = str(msg_id)
        while True:
            entries = await redis_connection.xrange(
                self.dlq_stream_name, min=cursor, count=DLQ_SCAN_BATCH_SIZE
            )
            for _entry_id, entry_fields in entries:
                if str(entry_fields.get("original_id", "")) == target_id:
                    return True
            if len(entries) < DLQ_SCAN_BATCH_SIZE:
                return False
            # Borne exclusive native Redis "(<id>" : lot suivant strictement après la dernière entrée lue
            cursor = f"({entries[-1][0]}"

    async def _send_to_dlq(
        self,
        redis_connection: Redis,
        msg_id: str,
        fields: dict[str, Any],
        reason: str,
        error: Optional[str] = None,
        *,
        skip_retention_check: bool = False,
    ) -> bool:
        """Push a message to the Dead Letter Queue (DLQ) stream.

        Args:
            msg_id: original message id in the source stream
            fields: original message fields (from Redis XREADGROUP)
            reason: short code describing why it was sent to DLQ (e.g., 'decode_error')
            error: optional error string/details
            skip_retention_check: true when the caller already verified DLQ retention
        """
        if not skip_retention_check:
            try:
                if await self._already_retained_in_dlq(redis_connection, msg_id):
                    logger.info(
                        f"Message {msg_id} already retained in DLQ stream '{self.dlq_stream_name}'; skipping duplicate write"
                    )
                    return True
            except Exception as scan_err:
                logger.error(
                    f"Failed to scan DLQ stream '{self.dlq_stream_name}' for {msg_id}: {scan_err}"
                )
                return False
        dlq_fields: dict[FieldT, EncodableT] = {
            "data": str(fields.get("data", "")),
            "retries": str(fields.get("retries", "0")),
            "original_id": str(msg_id),
            "reason": reason,
            "error": error or "",
            "consumer": self.consumer_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            dlq_id = await redis_connection.xadd(self.dlq_stream_name, dlq_fields)
            logger.info(
                f"Pushed message {msg_id} to DLQ stream '{self.dlq_stream_name}' with id {dlq_id} (reason={reason})"
            )
            return True
        except Exception as dlq_err:
            logger.error(f"Failed to push message {msg_id} to DLQ: {dlq_err}")
            return False

    # Récupère les messages en attente inactifs depuis plus de RECLAIM_IDLE_MS
    # et les remet en file pour traitement (xautoclaim puis xadd).
    # Convention partagée avec le chemin d'erreur du worker : le champ « retries »
    # compte les tentatives déjà consommées et max_retry_number est le nombre total
    # de tentatives autorisées. Une récupération consomme une seule tentative ;
    # toute entrée déjà conservée dans la DLQ (quel que soit son nombre de
    # tentatives) est immédiatement acquittée sans remise en file, et une entrée
    # épuisée ou invalide est conservée dans la DLQ puis acquittée uniquement
    # après conservation confirmée.
    async def _reclaim_pending_messages(self) -> None:
        logger.info(f"Reclaimer task started idle_ms = {RECLAIM_IDLE_MS}")
        start = "0-0"

        self.redis = await self._get_safe_redis_connection()

        # Boucle continue jusqu'à stop_flag
        while not self.stop_flag.is_set():
            try:
                next_start, claimed, _ = await self.redis.xautoclaim(
                    self.stream_name,
                    self.consumer_group,
                    self.consumer_name,
                    RECLAIM_IDLE_MS,
                    start,
                    count=1,
                )
                for msg_id, fields in claimed:
                    logger.info(f"Reclaimed message ID: {msg_id} with fields: {fields}")
                    try:
                        already_retained = await self._already_retained_in_dlq(
                            self.redis, msg_id
                        )
                    except Exception as scan_err:
                        logger.error(
                            f"Failed to scan DLQ stream '{self.dlq_stream_name}' for reclaimed message {msg_id}: {scan_err}"
                        )
                        continue

                    if already_retained:
                        logger.info(
                            f"Message {msg_id} already retained in DLQ stream '{self.dlq_stream_name}'; skipping duplicate write"
                        )
                        try:
                            await self.redis.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                        except Exception:
                            logger.error(
                                f"ACK failed for reclaimed DLQ message {msg_id}"
                            )
                        continue

                    if not fields or "data" not in fields:
                        logger.error(
                            f"Missing 'data' field for reclaimed message {msg_id}. Moving to DLQ."
                        )
                        if await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields or {},
                            reason="decode_error",
                            error="Missing 'data' field in reclaimed message",
                            skip_retention_check=True,
                        ):
                            try:
                                await self.redis.xack(
                                    self.stream_name, self.consumer_group, msg_id
                                )
                            except Exception:
                                logger.error(
                                    f"ACK failed for reclaimed decode_error message {msg_id}"
                                )
                        continue

                    try:
                        retry_count = self._parse_retry_count(fields)
                    except Exception as parse_err:
                        logger.error(
                            f"Invalid retries metadata for reclaimed message {msg_id}: {parse_err}. Moving to DLQ."
                        )
                        if await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="decode_error",
                            error=str(parse_err),
                            skip_retention_check=True,
                        ):
                            try:
                                await self.redis.xack(
                                    self.stream_name, self.consumer_group, msg_id
                                )
                            except Exception:
                                logger.error(
                                    f"ACK failed for reclaimed decode_error message {msg_id}"
                                )
                        continue

                    attempts = retry_count + 1
                    if attempts >= self.max_retry_number:
                        logger.error(
                            f"Max attempts exceeded for reclaimed message {msg_id}. Moving to DLQ."
                        )
                        if await self._send_to_dlq(
                            redis_connection=self.redis,
                            msg_id=msg_id,
                            fields=fields,
                            reason="max_retries_exceeded",
                            error="Exceeded max retry count during reclaim",
                            skip_retention_check=True,
                        ):
                            try:
                                await self.redis.xack(
                                    self.stream_name, self.consumer_group, msg_id
                                )
                            except Exception:
                                logger.error(
                                    f"ACK failed for reclaimed DLQ message {msg_id}"
                                )
                        continue

                    try:
                        requeued_fields = {**fields, "retries": str(attempts)}
                        await self.redis.xadd(self.stream_name, requeued_fields)
                        logger.info(f"Add new message with fields: {requeued_fields}")
                        try:
                            await self.redis.xack(
                                self.stream_name, self.consumer_group, msg_id
                            )
                            logger.info(f"Acknowledged reclaimed message {msg_id}")
                        except Exception:
                            logger.error(f"ACK failed for reclaimed {msg_id}")
                    except Exception as requeue_err:
                        logger.error(
                            f"Failed to requeue reclaimed message {msg_id}: {requeue_err}"
                        )
                start = next_start or "0-0"
                # Petit sleep coopératif
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reclaiming pending messages: {e}")
                await asyncio.sleep(5)
                continue
        logger.info("Reclaimer task stopped")
