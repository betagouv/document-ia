import asyncio
from threading import Thread
from typing import Optional, Awaitable


class AsyncThread:
    def __init__(self, target: Awaitable[None], name: str, daemon: bool = False):
        self._target = target
        self.name = name
        self.daemon = daemon
        self.thread: Optional[Thread] = None

    def start(self):
        loop_main = asyncio.get_running_loop()
        done_future = loop_main.create_future()

        def _runner():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._target)
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as e:
                loop_main.call_soon_threadsafe(done_future.set_exception, e)
            else:
                loop_main.call_soon_threadsafe(done_future.set_result, None)
            finally:
                loop.close()

        self.thread = Thread(target=_runner, name=self.name, daemon=self.daemon)
        self.thread.start()
        return done_future

    def join(self, timeout: float | None = None):
        if self.thread:
            self.thread.join(timeout)
