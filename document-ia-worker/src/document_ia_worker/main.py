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
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_worker.config.logging import setup_logging
from document_ia_worker.workflow.message_handler import process_message

setup_logging()
logger = logging.getLogger(__name__)

# Configure CPU thread limits for C libraries to avoid RAM bloating in Scalingo containers
try:
    import torch

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "1")))
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(1)
except Exception:
    pass

try:
    import cv2

    cv2.setNumThreads(int(os.environ.get("OPENCV_FOR_THREADS_NUM", "1")))
except Exception:
    pass


shutdown_flag = Event()
CONSUMER_SHUTDOWN_TIMEOUT_S = 30
CANCELLATION_CLEANUP_TIMEOUT_S = 5


def _force_exit() -> None:
    logger.critical("Forcing worker exit; unfinished messages remain pending")
    os._exit(1)


# Instance globale pour permettre au handler de signal d'appeler stop_signal
_consumer: Optional[Consumer[WorkflowExecutionMessage]] = None


def _prewarm_models() -> None:
    logger.info("[boot] Pre-warming AI models (YOLO-World & QRDet)...")
    try:
        from document_ia_worker.core.preprocessing.yoloworld_crop import (
            get_yoloworld_model,
        )

        get_yoloworld_model()
        logger.info("[boot]   ✅ YOLO-World model pre-loaded into RAM")
    except Exception as e:
        logger.warning(f"[boot]   ⚠️ Could not pre-load YOLO-World model: {e}")

    try:
        from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
            _get_qrdet_detector,
        )

        _get_qrdet_detector()
        logger.info("[boot]   ✅ QRDet model pre-loaded into RAM")
    except Exception as e:
        logger.warning(f"[boot]   ⚠️ Could not pre-load QRDet model: {e}")


async def run_consumer(stop_event: asyncio.Event | None = None) -> None:
    global _consumer
    logger.info("--- Starting document-ia-worker ---")
    _prewarm_models()
    logger.info("Register redis stream consumer for workflow execution")

    # This runtime owns the main-loop Redis pool; the consumer borrows it.
    redis_manager = RedisManager()
    _consumer = Consumer[WorkflowExecutionMessage](
        consumer_name=f"document-ia-worker:{os.getpid()}:{int(time.time()) % 10000}",
        consumer_group=redis_settings.EVENT_CONSUMER_GROUP,
        stream_name=redis_settings.EVENT_STREAM_NAME,
        batch_size=10,
        block_time=10000,
        message_class=WorkflowExecutionMessage,
        process_message_callable=process_message,
        current_redis_manager=redis_manager,
    )

    if stop_event is not None and stop_event.is_set():
        _consumer.stop_flag.set()

    try:
        await _consumer.start_consumer()
    finally:
        try:
            await asyncio.wait_for(redis_manager.close(), timeout=5)
        except Exception as exc:
            logger.warning("Failed to close worker Redis resources: %s", exc)


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

    consumer_task = asyncio.create_task(run_consumer(stop_event))

    stop_wait = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {consumer_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED
    )

    if consumer_task in done:
        stop_wait.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_wait
        try:
            await consumer_task
        except Exception:
            logger.error("❌ Consumer crashed — exiting with error")
            if _consumer is not None and _consumer.has_running_handlers:
                _force_exit()
            raise
        if stop_event.is_set() and _consumer is not None:
            if _consumer.has_running_handlers:
                _force_exit()
        return

    logger.info("Shutdown requested; stopping consumer")
    if _consumer is not None:
        _consumer.stop_flag.set()
    done, _ = await asyncio.wait({consumer_task}, timeout=CONSUMER_SHUTDOWN_TIMEOUT_S)
    if consumer_task in done:
        await consumer_task
        if _consumer is not None and _consumer.has_running_handlers:
            _force_exit()
        return

    logger.warning("Consumer shutdown timed out; cancelling remaining tasks")
    consumer_task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.shield(consumer_task), timeout=CANCELLATION_CLEANUP_TIMEOUT_S
        )
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        logger.warning(
            "Consumer cancellation timed out; unfinished messages remain pending"
        )
    _force_exit()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
