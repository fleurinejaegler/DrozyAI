"""Bridge Flask's request threads to the single-owner asynchronous runtime."""
import asyncio
from threading import Thread

from .service import Runtime


class RuntimeRunner:
    def __init__(self, runtime=None):
        self.runtime = runtime or Runtime()
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self.loop.run_forever, name='drowsy-runtime', daemon=True)
        self.thread.start()
        self.call(self.runtime.start())
        self.closed = False

    def call(self, coroutine, timeout=3):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    async def _invoke(self, callback, args, kwargs):
        return callback(*args, **kwargs)

    def invoke(self, callback, *args, **kwargs):
        return self.call(self._invoke(callback, args, kwargs))

    def close(self):
        if not self.closed:
            self.closed = True
            self.call(self.runtime.stop(), timeout=5)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
            self.loop.close()
