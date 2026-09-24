"""
In-memory ring buffer of recent log records, backing the in-app log viewer
(GET /api/v2/logs).

Attached via LOGGING in settings.py (the ``ringbuffer`` handler) to both the
"cinefin" tree and the root logger, so application logs and surfaced
third-party warnings all land here.

LIMITATION: this is per-process. The production deployment is a single
runserver process (see etc/cinefin3.service), so one buffer sees everything.
Under a multi-worker gunicorn each worker would have its own buffer and the
viewer would only show whichever worker served the request — that setup would
need a shared store (DB rows like the Job log, or redis) instead.

This module is imported by dictConfig before Django apps load, so it must not
import anything Django.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime

MAX_RECORDS = 2000


def level_number(name: str | None, default: int = logging.INFO) -> int:
    """Map a level name ('INFO', 'warning', ...) to its numeric value."""
    return logging.getLevelNamesMapping().get(str(name or "").upper(), default)


class LogRingBuffer:
    """Thread-safe deque of log-record dicts with a monotonic sequence counter.

    The sequence counter lets pollers (the SSE stream) cheaply ask "anything
    new since seq N?" without tracking deque rotation.
    """

    def __init__(self, maxlen: int = MAX_RECORDS):
        self._records: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, record: dict) -> None:
        with self._lock:
            self._seq += 1
            record["seq"] = self._seq
            self._records.append(record)

    def snapshot(self, min_levelno: int = 0, after_seq: int = 0, limit: int | None = None) -> tuple[list[dict], int]:
        """Matching records (oldest first) plus the buffer's current sequence.

        Returning the sequence from inside the lock gives pollers a race-free
        cursor: records appended after this call always have a higher seq.
        """
        with self._lock:
            seq = self._seq
            records = [r for r in self._records if r["seq"] > after_seq and r["levelno"] >= min_levelno]
        if limit is not None and len(records) > limit:
            records = records[-limit:]
        return records, seq

    def clear(self) -> None:
        """Drop all records and restart the sequence (used by tests)."""
        with self._lock:
            self._records.clear()
            self._seq = 0


#: The process-wide buffer every BufferHandler instance feeds.
buffer = LogRingBuffer()


class BufferHandler(logging.Handler):
    """logging.Handler that appends records to the module-level ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Handler.format with no formatter set renders the message and
            # appends any traceback — exactly what the viewer wants.
            message = self.format(record)
            buffer.append(
                {
                    "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                    "level": record.levelname,
                    "levelno": record.levelno,
                    "logger": record.name,
                    "message": message,
                }
            )
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)
