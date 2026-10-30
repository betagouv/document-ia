import asyncio
import importlib

import pytest

worker_main = importlib.import_module("document_ia_worker.main")


@pytest.mark.asyncio
async def test_signal_stops_consumer_and_waits_for_shutdown(monkeypatch):
    monkeypatch.setattr(worker_main, "_consumer", None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class FakeConsumer:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **_kwargs):
            self.stop_flag = asyncio.Event()
            self.stopped = asyncio.Event()
            self.has_running_handlers = False

        async def start_consumer(self):
            await self.stop_flag.wait()
            self.stopped.set()

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main, "Consumer", FakeConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )

    await worker_main.main()

    consumer = worker_main._consumer
    assert consumer.stop_flag.is_set()
    assert consumer.stopped.is_set()


@pytest.mark.asyncio
async def test_signal_cancels_consumer_after_shutdown_deadline(monkeypatch):
    monkeypatch.setattr(worker_main, "_consumer", None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class StuckConsumer:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **_kwargs):
            self.stop_flag = asyncio.Event()

        async def start_consumer(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main, "Consumer", StuckConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )
    monkeypatch.setattr(worker_main, "CONSUMER_SHUTDOWN_TIMEOUT_S", 0.01)
    forced_exit = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    await asyncio.wait_for(worker_main.main(), timeout=1)

    assert forced_exit == [1]


@pytest.mark.asyncio
async def test_signal_forces_exit_if_handler_thread_is_still_running(monkeypatch):
    monkeypatch.setattr(worker_main, "_consumer", None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class RunningHandlerConsumer:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **_kwargs):
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = True

        async def start_consumer(self):
            await self.stop_flag.wait()

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main, "Consumer", RunningHandlerConsumer)
    monkeypatch.setattr(
        worker_main, "_register_signal_handlers", lambda event: event.set()
    )
    forced_exit = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    await worker_main.main()

    assert forced_exit == [1]


@pytest.mark.asyncio
async def test_consumer_crash_forces_exit_if_handler_thread_is_still_running(
    monkeypatch,
):
    monkeypatch.setattr(worker_main, "_consumer", None)
    monkeypatch.setattr(worker_main.logger, "disabled", True)

    class CrashedConsumer:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **_kwargs):
            self.stop_flag = asyncio.Event()
            self.has_running_handlers = True

        async def start_consumer(self):
            raise RuntimeError("consumer failed")

    monkeypatch.setattr(worker_main, "_prewarm_models", lambda: None)
    monkeypatch.setattr(worker_main, "Consumer", CrashedConsumer)
    monkeypatch.setattr(worker_main, "_register_signal_handlers", lambda _event: None)
    forced_exit = []
    monkeypatch.setattr(worker_main, "_force_exit", lambda: forced_exit.append(1))

    with pytest.raises(RuntimeError, match="consumer failed"):
        await worker_main.main()

    assert forced_exit == [1]
