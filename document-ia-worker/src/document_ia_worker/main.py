import asyncio
import logging
import os
import time
import signal
from asyncio import Event
from types import FrameType
from typing import Iterable, Optional

from config.logging import setup_logging
from document_ia_redis.consumer import Consumer
from document_ia_redis.model.workflow_execution_message import WorkflowExecutionMessage
from document_ia_redis.redis_settings import redis_settings

setup_logging()
logger = logging.getLogger(__name__)

shutdown_flag = Event()

# Instance globale pour permettre au handler de signal d'appeler stop_signal
_consumer: Optional[Consumer[WorkflowExecutionMessage]] = None


async def run_consumer() -> None:
    global _consumer
    logger.info("--- Starting document-ia-worker ---")
    logger.info("Register redis stream consumer for workflow execution")

    _consumer = Consumer[WorkflowExecutionMessage](
        consumer_name=f"document-ia-worker:{os.getpid()}:{int(time.time()) % 10000}",
        consumer_group=redis_settings.EVENT_CONSUMER_GROUP,
        stream_name=redis_settings.EVENT_STREAM_NAME,
        batch_size=1,
        block_time=10000,
    )

    await _consumer.start_consumer()


def _register_signal_handlers(
    stop_event: asyncio.Event, sigs: Iterable[int] = (signal.SIGINT, signal.SIGTERM)
) -> None:
    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("Signal %s reçu, arrêt demandé.", signum)
        # Demande d'arrêt du consumer si instancié
        if _consumer is not None:
            _consumer.stop_signal()
        stop_event.set()

    for s in sigs:
        try:
            signal.signal(s, _handle_signal)
        except (ValueError, RuntimeError):
            logger.warning(
                "Impossible d'enregistrer le handler pour le signal %s (environnement non supporté)",
                s,
            )
            continue


async def main() -> None:
    stop_event = asyncio.Event()
    _register_signal_handlers(stop_event)

    consumer_task = asyncio.create_task(run_consumer())

    await stop_event.wait()

    logger.info("Arrêt en cours, cancellation du consumer...")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        logger.info("Consumer annulé proprement.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
