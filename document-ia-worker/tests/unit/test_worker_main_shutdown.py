"""Unit tests for document_ia_worker.main graceful shutdown and crash handling."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_worker_main_sigterm_waits_for_consumer_graceful_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lors de la réception de SIGTERM, main() doit lever _consumer.stop_flag et
    attendre la fin réelle de start_consumer() (vidange + cleanup) avant de rendre
    la main."""
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)

    started = asyncio.Event()
    drain_completed = False

    class FakeConsumer[T]:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = False

        async def start_consumer(self) -> None:
            nonlocal drain_completed
            started.set()
            await self.stop_flag.wait()
            # Simule le temps de vidange d'une tâche en vol avant la fin de start_consumer
            await asyncio.sleep(0.08)
            drain_completed = True

    monkeypatch.setattr(worker_main, "ThreadConsumer", FakeConsumer)

    main_task = asyncio.create_task(worker_main.main())
    await asyncio.wait_for(started.wait(), timeout=2.0)

    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(main_task, timeout=2.0)

    assert drain_completed is True
    assert worker_main._consumer is None


@pytest.mark.asyncio
async def test_worker_main_propagates_consumer_crash_and_cancels_stop_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si run_consumer() échoue de façon inattendue, main() annule stop_wait et
    relève l'exception sans laisser de tâche pendante."""
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)

    class CrashingConsumer[T]:
        def __init__(self, **_kwargs: Any) -> None:
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = False

        async def start_consumer(self) -> None:
            raise RuntimeError("boom in start_consumer")

    monkeypatch.setattr(worker_main, "ThreadConsumer", CrashingConsumer)

    with pytest.raises(RuntimeError, match="boom in start_consumer"):
        await asyncio.wait_for(worker_main.main(), timeout=2.0)

    assert worker_main._consumer is None


@pytest.mark.asyncio
async def test_signal_stops_consumer_and_waits_for_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    created_consumers = []

    class FakeConsumer[T]:
        def __init__(self, **_kwargs: Any) -> None:
            self.stop_flag = asyncio.Event()
            self.stopped = asyncio.Event()
            self.has_running_handlers = False
            created_consumers.append(self)

        async def start_consumer(self) -> None:
            await self.stop_flag.wait()
            self.stopped.set()

    monkeypatch.setattr(worker_main, "ThreadConsumer", FakeConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )

    await worker_main.main()

    assert len(created_consumers) == 1
    consumer = created_consumers[0]
    assert consumer.stop_flag.is_set()
    assert consumer.stopped.is_set()


@pytest.mark.asyncio
async def test_signal_cancels_consumer_after_shutdown_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class StuckConsumer[T]:
        def __init__(self, **_kwargs: Any) -> None:
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = False

        async def start_consumer(self) -> None:
            await asyncio.Event().wait()

    monkeypatch.setattr(worker_main, "ThreadConsumer", StuckConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )
    monkeypatch.setattr(worker_main, "CONSUMER_SHUTDOWN_TIMEOUT_S", 0.01)
    monkeypatch.setattr(worker_main, "CANCELLATION_CLEANUP_TIMEOUT_S", 0.01)
    forced_exit: list[int] = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    await asyncio.wait_for(worker_main.main(), timeout=1)

    assert forced_exit == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_runtime_closes_owned_redis_manager(monkeypatch, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from document_ia_worker import main as worker_main

    owner = SimpleNamespace(close=AsyncMock())
    passed_managers = []

    class Consumer:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **kwargs):
            passed_managers.append(kwargs["current_redis_manager"])

        async def start_consumer(self):
            if outcome == "error":
                raise RuntimeError("handler failed")
            if outcome == "cancel":
                raise asyncio.CancelledError

    monkeypatch.setattr(worker_main, "_consumer", None)
    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main, "RedisManager", lambda: owner)
    monkeypatch.setattr(worker_main, "ThreadConsumer", Consumer)
    if outcome == "success":
        await worker_main.run_consumer()
    else:
        exception = RuntimeError if outcome == "error" else asyncio.CancelledError
        with pytest.raises(exception):
            await worker_main.run_consumer()
    assert passed_managers == [owner]
    owner.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_signal_forces_exit_if_handler_thread_is_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class RunningHandlerConsumer[T]:
        def __init__(self, **_kwargs: Any) -> None:
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = True

        async def start_consumer(self) -> None:
            await self.stop_flag.wait()

    monkeypatch.setattr(worker_main, "ThreadConsumer", RunningHandlerConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )
    forced_exit: list[int] = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    await worker_main.main()

    assert forced_exit == [1]


@pytest.mark.asyncio
async def test_consumer_crash_forces_exit_if_handler_thread_is_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_ia_worker import main as worker_main

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class CrashedConsumer[T]:
        def __init__(self, **_kwargs: Any) -> None:
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = True

        async def start_consumer(self) -> None:
            raise RuntimeError("consumer failed")

    monkeypatch.setattr(worker_main, "ThreadConsumer", CrashedConsumer)
    monkeypatch.setattr(worker_main, "_register_signal_handlers", lambda _event: None)
    forced_exit: list[int] = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    with pytest.raises(RuntimeError, match="consumer failed"):
        await worker_main.main()

    assert forced_exit == [1]
