import threading
import time
from typing import Any, Callable, Optional

from .dispatch_queue import DispatchQueue
from .event_envelope import EventEnvelope
from .lease import LeaseConflictError, LeaseManager
from .router import RouteDecision, RuleRouter


class LocalWorker:
    """A safe local worker that polls tasks via 50-second long-polling without exposing public ports."""

    def __init__(
        self,
        worker_id: str,
        queue: DispatchQueue,
        router: RuleRouter,
        lease_mgr: LeaseManager,
        pipeline_executor: Callable[[EventEnvelope, RouteDecision], Any],
        lease_ttl_seconds: float = 300.0,
    ):
        self.worker_id = worker_id
        self.queue = queue
        self.router = router
        self.lease_mgr = lease_mgr
        self.pipeline_executor = pipeline_executor
        self.lease_ttl_seconds = lease_ttl_seconds
        self._stop_event = threading.Event()

    def poll_and_execute_once(self, timeout: float = 50.0) -> Optional[Any]:
        """Polls the dispatch queue with long-polling timeout and executes under entity lease."""
        task = self.queue.poll(worker_id=self.worker_id, timeout=timeout)
        if task is None:
            return None

        route = self.router.match(task)

        try:
            lease = self.lease_mgr.acquire_lease(
                target=task.target,
                worker_id=self.worker_id,
                ttl_seconds=self.lease_ttl_seconds,
            )
        except LeaseConflictError:
            self.queue.nack(task.event_id, requeue=True)
            raise

        try:
            result = self.pipeline_executor(task, route)
            self.queue.ack(task.event_id)
            return result
        except Exception:
            self.queue.nack(task.event_id, requeue=False)
            raise
        finally:
            self.lease_mgr.release_lease(task.target, lease.token)

    def stop(self) -> None:
        """Signal the worker to terminate gracefully."""
        self._stop_event.set()
