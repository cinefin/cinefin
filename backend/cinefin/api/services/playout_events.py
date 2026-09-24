"""Playout event bus — in-process wake-signal pub/sub for the playout SSE stream.

The bus carries only wake signals, not payloads: each SSE connection rebuilds the
current snapshot on wake, so a slow/paused client can never accumulate stale frames.
Single-process only — under multiple gunicorn workers each worker has its own bus."""

import queue
import threading


class PlayoutEventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(1)
            except queue.Full:
                pass


playout_event_bus = PlayoutEventBus()
