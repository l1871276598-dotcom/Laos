import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


class LeaseConflictError(Exception):
    """Raised when an attempt to acquire a lease fails due to an existing unexpired lock on the entity."""
    pass


@dataclass
class LeaseInfo:
    target: str
    worker_id: str
    acquired_at: float
    ttl_seconds: float
    token: str = field(default_factory=lambda: uuid.uuid4().hex)

    def is_expired(self, now: Optional[float] = None) -> bool:
        current_time = time.monotonic() if now is None else now
        return (current_time - self.acquired_at) >= self.ttl_seconds


class LeaseManager:
    """Thread-safe single-writer entity lease coordinator with TTL auto-recovery."""

    def __init__(self):
        self._lock = threading.Lock()
        self._leases: Dict[str, LeaseInfo] = {}

    def acquire_lease(
        self,
        target: str,
        worker_id: str,
        ttl_seconds: float = 300.0,
    ) -> LeaseInfo:
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(target)

            if existing is not None:
                if not existing.is_expired(now) and existing.worker_id != worker_id:
                    remaining = existing.ttl_seconds - (now - existing.acquired_at)
                    raise LeaseConflictError(
                        f"Target '{target}' is currently locked by worker '{existing.worker_id}' "
                        f"for another {remaining:.1f}s."
                    )

            lease = LeaseInfo(
                target=target,
                worker_id=worker_id,
                acquired_at=now,
                ttl_seconds=ttl_seconds,
            )
            self._leases[target] = lease
            return lease

    def release_lease(self, target: str, token: str) -> bool:
        with self._lock:
            existing = self._leases.get(target)
            if existing is not None and existing.token == token:
                del self._leases[target]
                return True
            return False

    def is_locked(self, target: str) -> bool:
        with self._lock:
            now = time.monotonic()
            existing = self._leases.get(target)
            if existing is None:
                return False
            if existing.is_expired(now):
                del self._leases[target]
                return False
            return True
