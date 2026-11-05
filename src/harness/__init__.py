"""LAOS Agent Harness - Production Execution Kernel.

Follows the Khazix Agent-Autoloop paradigm:
- Minimal kernel (< 1600 LOC)
- Standard-library-only execution
- Append-only event sourcing
- Hop-count fuse (TTL) circuit breaking
- Trailing control envelope parsing
- Suspend-zero-cost process management
"""

from .envelope import (
    CircuitBreakerTrippedError,
    EnvelopeMalformedError,
    EnvelopeMissingError,
    parse_envelope,
    serialize_envelope,
    strip_envelope,
)
from .journal import AppendOnlyJournal, JournalTamperError
from .pipeline import HarnessPipeline, PipelineResult, PipelineStatus
from .probe import TruthProbe
from .review_gate import (
    Finding,
    FindingSeverity,
    ReviewGate,
    ReviewRequest,
    ReviewResponse,
)
from .sandbox import (
    EphemeralSandbox,
    SandboxExecutionError,
    SandboxTimeoutError,
    WorktreeSandbox,
)
from .types import (
    JournalEvent,
    PhysicalWitness,
    SandboxResult,
    TrailingEnvelope,
    Verdict,
)

__all__ = [
    "AppendOnlyJournal",
    "CircuitBreakerTrippedError",
    "EnvelopeMalformedError",
    "EnvelopeMissingError",
    "EphemeralSandbox",
    "Finding",
    "FindingSeverity",
    "HarnessPipeline",
    "JournalEvent",
    "JournalTamperError",
    "PhysicalWitness",
    "PipelineResult",
    "PipelineStatus",
    "ReviewGate",
    "ReviewRequest",
    "ReviewResponse",
    "SandboxExecutionError",
    "SandboxResult",
    "SandboxTimeoutError",
    "TrailingEnvelope",
    "TruthProbe",
    "Verdict",
    "WorktreeSandbox",
    "parse_envelope",
    "serialize_envelope",
    "strip_envelope",
]
