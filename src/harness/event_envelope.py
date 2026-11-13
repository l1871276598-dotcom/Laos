import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class DuplicateEventIgnored(Exception):
    """Raised when an incoming event has already been processed according to its idempotency hash."""
    pass


@dataclass
class EventEnvelope:
    source: str
    event_type: str
    target: str
    payload: Dict[str, Any]
    dedup_key: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    summary: str = ""
    context_url: str = ""

    def __post_init__(self):
        if not str(self.source).strip():
            raise ValueError("EventEnvelope 'source' must be a non-empty string.")
        if not str(self.event_type).strip():
            raise ValueError("EventEnvelope 'event_type' must be a non-empty string.")
        if not str(self.target).strip():
            raise ValueError("EventEnvelope 'target' must be a non-empty string.")
        if not str(self.dedup_key).strip():
            raise ValueError("EventEnvelope 'dedup_key' must be a non-empty string.")

    def compute_dedup_hash(self) -> str:
        """Computes a deterministic SHA-256 hash across the canonical (source, event_type, target, dedup_key) tuple."""
        canonical_tuple = [
            self.source.strip(),
            self.event_type.strip(),
            self.target.strip(),
            self.dedup_key.strip(),
        ]
        raw_bytes = json.dumps(canonical_tuple, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()


class IdempotencyFilter:
    """In-memory thread-safe idempotency ledger with TTL-based expiration."""

    def __init__(self, ttl_seconds: float = 86400.0):
        self.ttl_seconds = ttl_seconds
        self._seen: Dict[str, float] = {}

    def _purge_expired(self, now: float) -> None:
        expired_keys = [k for k, ts in self._seen.items() if now - ts > self.ttl_seconds]
        for k in expired_keys:
            del self._seen[k]

    def is_duplicate(self, envelope: EventEnvelope) -> bool:
        h = envelope.compute_dedup_hash()
        now = time.monotonic()
        self._purge_expired(now)
        return h in self._seen

    def check_and_record(self, envelope: EventEnvelope) -> bool:
        """Verifies whether the event has been seen. If seen, raises DuplicateEventIgnored; otherwise records it."""
        h = envelope.compute_dedup_hash()
        now = time.monotonic()
        self._purge_expired(now)

        if h in self._seen:
            raise DuplicateEventIgnored(
                f"Event with dedup_hash '{h}' (source={envelope.source}, dedup_key={envelope.dedup_key}) was already processed."
            )

        self._seen[h] = now
        return True
