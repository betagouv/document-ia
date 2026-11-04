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

        async def start_consumer(self) -> None:
            raise RuntimeError("boom in start_consumer")

    monkeypatch.setattr(worker_main, "ThreadConsumer", CrashingConsumer)

    with pytest.raises(RuntimeError, match="boom in start_consumer"):
        await asyncio.wait_for(worker_main.main(), timeout=2.0)

    assert worker_main._consumer is None
