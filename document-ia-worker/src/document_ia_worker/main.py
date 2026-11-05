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
from document_ia_infra.redis.redis_manager import RedisManager
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


CONSUMER_SHUTDOWN_TIMEOUT_S = 22
CANCELLATION_CLEANUP_TIMEOUT_S = 3


def _force_exit() -> None:
    logger.critical("Forcing worker exit; unfinished messages remain pending")
    os._exit(1)


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
    logger.info("Register redis stream consumer for workflow execution")

    # This runtime owns the main-loop Redis pool; the consumer borrows it.
    redis_manager = RedisManager()
    _consumer = ThreadConsumer[WorkflowExecutionMessage](
        consumer_name=build_instance_consumer_name("document-ia-worker"),
        consumer_group=redis_settings.EVENT_CONSUMER_GROUP,
        stream_name=redis_settings.EVENT_STREAM_NAME,
        batch_size=10,
        block_time=10000,
        message_class=WorkflowExecutionMessage,
        process_message_callable=process_message,
        reclaim_poll_interval_s=5.0,
        current_redis_manager=redis_manager,
        max_processing_time_s=120.0,
        step_progress_timeout_s=90.0,
        use_execution_lease=True,
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

        # Un signal d'arrêt (SIGINT / SIGTERM) a été reçu : arrêt gracieux
        logger.info("Shutdown requested; stopping consumer")
        if _consumer is not None:
            _consumer.stop_flag.set()
        done, _ = await asyncio.wait(
            {consumer_task}, timeout=CONSUMER_SHUTDOWN_TIMEOUT_S
        )
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
        except TimeoutError:
            logger.warning(
                "Consumer cancellation timed out; unfinished messages remain pending"
            )
        _force_exit()
    finally:
        loop = asyncio.get_running_loop()
        for s in registered_sigs or ():
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
