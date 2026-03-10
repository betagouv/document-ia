import asyncio
import contextlib
import logging
import os
import signal
import time
from asyncio import Event
from types import FrameType
from typing import Iterable, Optional

from document_ia_infra.redis.consumer import Consumer
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_worker.config.logging import setup_logging
from document_ia_worker.workflow.message_handler import process_message

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
        batch_size=10,
        block_time=10000,
        message_class=WorkflowExecutionMessage,
        process_message_callable=process_message,
    )

    await _consumer.start_consumer()


def _register_signal_handlers(
    stop_event: asyncio.Event, sigs: Iterable[int] = (signal.SIGINT, signal.SIGTERM)
) -> None:
    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
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

    stop_wait = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {consumer_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED
    )

    if consumer_task in done:
        # Le consumer est terminé (erreur ou fin normale)
        try:
            await consumer_task
        except Exception:
            logger.error("❌ Consumer crashed — exiting with error")
            raise
    else:
        logger.info("Consumer finished gracefully - exiting")
        return

    if _consumer is not None:
        _consumer.stop_flag.set()
    try:
        await asyncio.wait_for(consumer_task, timeout=20)
    except asyncio.TimeoutError:
        logger.warning("Consumer timed out - exiting")
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
