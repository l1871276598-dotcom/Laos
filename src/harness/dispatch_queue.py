import threading
import time
from typing import Dict, List, Optional, Tuple

from .event_envelope import EventEnvelope


class DispatchQueue:
    """A thread-safe in-memory task dispatch queue with 50-second long-polling synchronization."""

    def __init__(self):
        self._cond = threading.Condition()
        self._queue: List[EventEnvelope] = []
        self._in_flight: Dict[str, Tuple[str, float, EventEnvelope]] = {}

    def enqueue(self, envelope: EventEnvelope) -> str:
        with self._cond:
            self._queue.append(envelope)
            self._cond.notify()
            return envelope.event_id

    def poll(self, worker_id: str, timeout: float = 50.0) -> Optional[EventEnvelope]:
        with self._cond:
            deadline = time.monotonic() + timeout
            while len(self._queue) == 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)

            task = self._queue.pop(0)
            self._in_flight[task.event_id] = (worker_id, time.monotonic(), task)
            return task

    def ack(self, event_id: str) -> None:
        with self._cond:
            self._in_flight.pop(event_id, None)

    def nack(self, event_id: str, requeue: bool = True) -> None:
        with self._cond:
            entry = self._in_flight.pop(event_id, None)
            if entry is not None and requeue:
                _, _, task = entry
                self._queue.insert(0, task)
                self._cond.notify()

    def qsize(self) -> int:
        with self._cond:
            return len(self._queue)
