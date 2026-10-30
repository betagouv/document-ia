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

from redis import ResponseError
from redis.asyncio import Redis
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

# Script Lua de remise en file atomique et idempotente.
#
# Une remise en file crée une copie de l'entrée d'origine (avec le champ
# « original_id ») puis l'acquitte. Sans garde atomique, un acquittement en
# échec laisse l'original en attente et chaque récupération crée une copie
# supplémentaire. La solution naïve — une clé d'index `SET NX` posée avant le
# XADD — est pire : une réservation orpheline (crash entre la réservation et
# la copie) fait croire à une copie existante et laisse un autre reclaimer
# acquitter l'original sans jamais le recopier (perte de message).
#
# Le script rend la vérification et la copie atomiques : il recherche une
# copie portant « original_id » et n'en crée une que si aucune n'existe. Il
# n'y a donc pas de réservation séparée à orpheliner, et une réponse perdue
# (le XADD a réussi mais le client n'a pas reçu la réponse) ne crée pas de
# doublon à la tentative suivante : la copie est retrouvée.
#
# Retour : {created_flag, id} — created_flag vaut 1 si une copie a été créée,
# 0 si une copie existait déjà ; id est l'identifiant de la copie.
_REQUEUE_LUA = """
local stream = KEYS[1]
local orig = ARGV[1]
local retries = ARGV[2]
local data = ARGV[3]
local existing = redis.call('XRANGE', stream, orig, '+')
for _, e in ipairs(existing) do
  local f = e[2]
  for i = 1, #f, 2 do
    if f[i] == 'original_id' and f[i+1] == orig then
      return {0, e[1]}
    end
  end
end
local id = redis.call('XADD', stream, '*', 'data', data, 'retries', retries, 'original_id', orig)
return {1, id}
"""

# Script Lua de conservation DLQ atomique et idempotente, même principe :
# recherche d'une entrée DLQ portant « original_id » puis XADD si absente.
# Les champs DLQ sont passés en paires clé/valeur après original_id.
_RETAIN_DLQ_LUA = """
local dlq = KEYS[1]
local orig = ARGV[1]
-- L'identifiant de l'entrée DLQ est indépendant de celui de l'entrée source
-- (flux différents, séquences indépendantes) : le parcours part de 0-0 pour
-- ne jamais manquer une copie déjà conservée, quelle que soit sa position.
local existing = redis.call('XRANGE', dlq, '0-0', '+')
for _, e in ipairs(existing) do
  local f = e[2]
  for i = 1, #f, 2 do
    if f[i] == 'original_id' and f[i+1] == orig then
      return {0, e[1]}
    end
  end
end
local args = {}
for i = 2, #ARGV do
  table.insert(args, ARGV[i])
end
local id = redis.call('XADD', dlq, '*', unpack(args))
return {1, id}
"""


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
        self._listener_done = asyncio.Event()
        self._draining = False

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
                self.heartbeat_task = tg.create_task(
                    self._heartbeat_in_flight_entries(),
                    name=f"heartbeat-{self.consumer_name}",
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

                # 4. Soumission des nouveaux messages.
                # Enregistrer TOUTES les entrées livrées avant le premier
                # await : une entrée en erreur de décodage peut bloquer sur
                # sa conservation DLQ, et les entrées suivantes du lot
                # resteraient non protégées contre une récupération.
                for msg_id, _fields in entries:
                    self._in_flight_ids.add(msg_id)
                for msg_id, fields in entries:
                    raw_data = fields.get("data")
                    retry_count = int(fields.get("retries", "0"))

                    try:
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
                        # L'entrée est terminée (conservée ou laissée en
                        # attente pour une prochaine récupération) : cesser
                        # de la protéger pour ne pas la garder indéfiniment.
                        self._in_flight_ids.discard(msg_id)
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
                done, pending = await asyncio.wait(active_futures.keys(), timeout=10)
                # Traiter les futures terminées pour ACK/DLQ
                for fut in done:
                    msg_id, fields = active_futures.pop(fut, (None, None))  # type: ignore
                    if msg_id is not None and fields is not None:
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
            self._draining = False
            self._listener_done.set()

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
            retry_count = int(fields.get("retries", "0"))
            data = fields.get("data", "")

            if retry_count < self.max_retry_number - 1:
                try:
                    # Copie atomique et idempotente : créée si absente,
                    # retrouvée sinon. L'acquittement n'a lieu que si la
                    # copie existe.
                    await self._requeue_once(
                        redis_connection, msg_id, str(data), retry_count + 1
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
        await redis_connection.eval(
            _REQUEUE_LUA, 1, self.stream_name, msg_id, str(retries), data
        )
        return True

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
        dlq_fields: dict[FieldT, EncodableT] = {
            "data": str(fields.get("data", "")),
            "retries": str(fields.get("retries", "0")),
            "original_id": str(msg_id),
            "reason": reason,
            "error": error or "",
            "consumer": self.consumer_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Paires clé/valeur après original_id pour le script Lua.
        argv: list[str] = [str(msg_id)]
        for key, value in dlq_fields.items():
            argv.append(str(key))
            argv.append(str(value))
        try:
            await redis_connection.eval(
                _RETAIN_DLQ_LUA, 1, self.dlq_stream_name, *argv
            )
            return True
        except Exception as dlq_err:
            logger.error(
                f"Failed to retain message {msg_id} in DLQ "
                f"'{self.dlq_stream_name}': {dlq_err}; leaving entry pending"
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
                next_start, claimed, _ = await self.redis.xautoclaim(
                    self.stream_name,
                    self.consumer_group,
                    self.consumer_name,
                    RECLAIM_IDLE_MS,
                    start,
                    count=1,
                )
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
                logger.error(f"Error reclaiming pending messages: {e}")
                await asyncio.sleep(5)
                continue
        logger.info("Reclaimer task stopped")

    async def _reclaim_entry(self, msg_id: str, fields: dict[str, Any]) -> None:
        """Retraite une entrée revendiquée : DLQ si épuisée, sinon remise en file."""
        logger.info(f"Reclaimed message ID: {msg_id} with fields: {fields}")
        try:
            attempts = int(fields.get("retries", "0")) + 1
        except (TypeError, ValueError):
            # Champ « retries » illisible : la tentative ne peut être comptée
            # ni la remise en file honorée. Conserver en DLQ plutôt que de
            # re-réclamer la même entrée indéfiniment.
            logger.error(
                f"Malformed retries field for reclaimed message {msg_id}: "
                f"{fields.get('retries')!r}. Moving to DLQ."
            )
            await self._retain_in_dlq_and_ack(
                msg_id,
                fields,
                "max_retries_exceeded",
                f"Malformed retries field: {fields.get('retries')!r}",
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
                await self.redis.xack(self.stream_name, self.consumer_group, msg_id)
                logger.info(f"Acknowledged reclaimed message {msg_id}")
            except Exception:
                logger.error(f"ACK failed for reclaimed {msg_id}")
        except Exception as requeue_err:
            logger.error(f"Failed to requeue reclaimed message {msg_id}: {requeue_err}")

    async def _retain_in_dlq_and_ack(
        self, msg_id: str, fields: dict[str, Any], reason: str, error: str
    ) -> None:
        """Conserve l'entrée en DLQ puis l'acquitte après conservation confirmée."""
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
            await self.redis.xack(self.stream_name, self.consumer_group, msg_id)
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
                await self.redis.xclaim(
                    self.stream_name,
                    self.consumer_group,
                    self.consumer_name,
                    min_idle_time=0,
                    message_ids=list(ids),
                    justid=True,
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
        logger.info("Heartbeat task stopped")
