"""Bounded thread execution for workflows containing synchronous/CPU work."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Coroutine
from typing import Any


def run_handler_in_thread(handler: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run one workflow on its own loop; resources must close inside handler.

    Runner cancels leftover tasks and closes async generators/default executor.
    It does not depend on GC/destructors scheduling HTTP client cleanup.
    """
    with asyncio.Runner() as runner:
        runner.run(handler())


class HandlerExecution:
    """Own the thread pool, never admit more than available handler slots."""

    def __init__(self, workers: int, batch_size: int):
        if workers < 1 or batch_size < 1:
            raise ValueError("workers and batch_size must be positive")
        self.workers = workers
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def read_capacity(self, active: int) -> int:
        return min(self.batch_size, max(0, self.workers - active))

    def close(self) -> None:
        # Python cannot interrupt running native/thread work. The process owner
        # enforces the hard deadline; pending Redis entries remain recoverable.
        self.executor.shutdown(wait=False, cancel_futures=True)
