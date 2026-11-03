import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Iterable
from types import FrameType

from document_ia_infra.redis.consumer import (
    ThreadConsumer,
    build_instance_consumer_name,
)
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_worker.config.logging import setup_logging
from document_ia_worker.workflow.message_handler import process_message

setup_logging()
logger = logging.getLogger(__name__)

# Configure CPU thread limits for C libraries to avoid RAM bloating in Scalingo containers
try:
    import torch

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "1")))  # pyright: ignore[reportPrivateImportUsage]
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(1)  # pyright: ignore[reportPrivateImportUsage]
except Exception:
    pass

try:
    import cv2

    cv2.setNumThreads(int(os.environ.get("OPENCV_FOR_THREADS_NUM", "1")))
except Exception:
    pass


# Instance globale pour permettre l'arrêt gracieux lors d'un signal système
_consumer: ThreadConsumer[WorkflowExecutionMessage] | None = None


def _prewarm_models() -> None:
    logger.info("[boot] Pre-warming AI models (YOLO-World & QRDet)...")
    try:
        from document_ia_worker.core.preprocessing.yoloworld_crop import (
            get_yoloworld_model,
        )

        get_yoloworld_model()
        logger.info("[boot]   ✅ YOLO-World model pre-loaded into RAM")
    except Exception as e:
        logger.warning("[boot]   ⚠️ Could not pre-load YOLO-World model: %s", e)

    try:
        from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
            _get_qrdet_detector,  # pyright: ignore[reportPrivateUsage]
        )

        _get_qrdet_detector()
        logger.info("[boot]   ✅ QRDet model pre-loaded into RAM")
    except Exception as e:
        logger.warning("[boot]   ⚠️ Could not pre-load QRDet model: %s", e)


async def run_consumer(stop_event: asyncio.Event | None = None) -> None:
    global _consumer
    logger.info("--- Starting document-ia-worker ---")
    _prewarm_models()
    if stop_event is not None and stop_event.is_set():
        logger.info("Shutdown requested during boot — skipping consumer startup")
        return
    logger.info("Register redis stream consumer for workflow execution")

    _consumer = ThreadConsumer[WorkflowExecutionMessage](
        consumer_name=build_instance_consumer_name("document-ia-worker"),
        consumer_group=redis_settings.EVENT_CONSUMER_GROUP,
        stream_name=redis_settings.EVENT_STREAM_NAME,
        batch_size=10,
        block_time=10000,
        message_class=WorkflowExecutionMessage,
        process_message_callable=process_message,
        reclaim_poll_interval_s=5.0,
    )
    if stop_event is not None and stop_event.is_set():
        _consumer.stop_flag.set()
        return

    await _consumer.start_consumer()


def _register_signal_handlers(
    stop_event: asyncio.Event,
    sigs: Iterable[int] = (signal.SIGINT, signal.SIGTERM),
) -> list[int]:
    loop = asyncio.get_running_loop()
    registered_loop_sigs: list[int] = []

    def _fallback_handler(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop_event.set)

    for s in sigs:
        try:
            loop.add_signal_handler(s, stop_event.set)
            registered_loop_sigs.append(s)
        except NotImplementedError:
            try:
                signal.signal(s, _fallback_handler)
            except (ValueError, RuntimeError):
                logger.warning(
                    "Impossible d'enregistrer le handler pour le signal %s (environnement non supporté)",
                    s,
                )
        except (ValueError, RuntimeError):
            logger.warning(
                "Impossible d'enregistrer le handler pour le signal %s (environnement non supporté)",
                s,
            )
    return registered_loop_sigs


async def main() -> None:
    global _consumer
    stop_event = asyncio.Event()
    registered_sigs = _register_signal_handlers(stop_event)

    consumer_task = asyncio.create_task(run_consumer(stop_event))
    stop_wait = asyncio.create_task(stop_event.wait())

    try:
        done, _ = await asyncio.wait(
            {consumer_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED
        )

        if consumer_task in done:
            # Le consumer s'est terminé de lui-même (erreur ou fin normale)
            try:
                await consumer_task
            except Exception:
                logger.error("❌ Consumer crashed — exiting with error")
                raise
            return

        # Un signal d'arrêt (SIGINT / SIGTERM) a été reçu : arrêt gracieux
        logger.info("Shutdown signal received — stopping consumer gracefully...")
        if _consumer is not None:
            _consumer.stop_flag.set()
        try:
            await asyncio.wait_for(consumer_task, timeout=25)
            logger.info("Consumer finished gracefully — exiting")
        except TimeoutError:
            logger.warning("Consumer timed out during shutdown — cancelling")
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
    finally:
        loop = asyncio.get_running_loop()
        for s in registered_sigs:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(s)
        if not stop_wait.done():
            stop_wait.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_wait
        _consumer = None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
