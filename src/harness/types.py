import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional


class Verdict(str, Enum):
    SHIP = "SHIP"
    FIX_FIRST = "FIX_FIRST"
    REJECT = "REJECT"

    @classmethod
    def from_str(cls, val: Any) -> "Verdict":
        if isinstance(val, cls):
            return val
        cleaned = (val.value if hasattr(val, "value") else str(val)).strip().upper()
        if "." in cleaned:
            cleaned = cleaned.split(".")[-1]
        for member in cls:
            if member.value == cleaned:
                return member
        return cls.REJECT


@dataclass
class JournalEvent:
    event_type: str
    payload: dict = field(default_factory=dict)
    entity_ids: List[str] = field(default_factory=list)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    checksum: str = ""

    def compute_checksum(self) -> str:
        canonical_content = [
            self.event_id,
            self.event_type,
            self.timestamp,
            sorted(list(self.entity_ids)),
            self.payload,
        ]
        raw_bytes = json.dumps(canonical_content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()


@dataclass
class TrailingEnvelope:
    verdict: Verdict | str
    ttl: int = 8
    findings: List[Any] = field(default_factory=list)
    requires_action: bool = False
    suggested_actions: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.verdict, Verdict):
            self.verdict = Verdict.from_str(self.verdict)

    def decrement_ttl(self) -> "TrailingEnvelope":
        from .envelope import CircuitBreakerTrippedError

        if self.ttl <= 1:
            raise CircuitBreakerTrippedError(
                f"Hop-count fuse tripped: TTL reached {self.ttl - 1} (<= 0). Cascade loop halted."
            )
        return TrailingEnvelope(
            verdict=self.verdict,
            ttl=self.ttl - 1,
            findings=list(self.findings),
            requires_action=self.requires_action,
            suggested_actions=list(self.suggested_actions),
        )


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    stdout_sha256: str
    stderr_sha256: str
    duration_ms: int
    environment_fingerprint: str = ""


@dataclass
class PhysicalWitness:
    pipeline_id: str
    step_id: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    wall_clock_duration_ms: int
    environment_fingerprint: str
    witness_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sealed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_valid: bool = True

    def compute_witness_digest(self) -> str:
        content = [
            self.witness_id,
            self.pipeline_id,
            self.step_id,
            self.exit_code,
            self.stdout_sha256,
            self.stderr_sha256,
            self.wall_clock_duration_ms,
            self.environment_fingerprint,
            self.sealed_at,
            self.is_valid,
        ]
        raw = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


