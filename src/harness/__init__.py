"""LAOS Agent Harness - Production Execution Kernel.

Follows the Khazix Agent-Autoloop & Karpathy Nano paradigm:
- Minimal kernel (< 1600 LOC)
- Standard-library-only execution
- Append-only event sourcing
- Hop-count fuse (TTL) circuit breaking
- Trailing control envelope parsing
- Suspend-zero-cost process management
- 50-second long-polling safe local worker
- Single-writer entity lease concurrency lock
- Event envelope & idempotency deduplication
- 7-category high-risk Kill Gate
- Immutable decision ledger ("Never Ask Twice")
- Interactive approval card generation
"""

from .approval_card import ApprovalCard
from .decision_ledger import (
    DecisionLedger,
    DecisionRecord,
    DecisionType,
    NegativeDirectiveViolationError,
)
from .dispatch_queue import DispatchQueue
from .envelope import (
    CircuitBreakerTrippedError,
    EnvelopeMalformedError,
    EnvelopeMissingError,
    parse_envelope,
    serialize_envelope,
    strip_envelope,
)
from .event_envelope import (
    DuplicateEventIgnored,
    EventEnvelope,
    IdempotencyFilter,
)
from .journal import AppendOnlyJournal, JournalTamperError
from .kill_gate import (
    ActionProposal,
    KillCategory,
    KillGate,
    KillGateInterceptedError,
    KillInterceptResult,
)
from .lease import LeaseConflictError, LeaseInfo, LeaseManager
from .pipeline import HarnessPipeline, PipelineResult, PipelineStatus
from .probe import TruthProbe
from .review_gate import (
    Finding,
    FindingSeverity,
    ReviewGate,
    ReviewRequest,
    ReviewResponse,
)
from .router import RouteDecision, RuleRouter, UnmatchedRouteError
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
from .worker import LocalWorker

__all__ = [
    "ActionProposal",
    "AppendOnlyJournal",
    "ApprovalCard",
    "CircuitBreakerTrippedError",
    "DecisionLedger",
    "DecisionRecord",
    "DecisionType",
    "DispatchQueue",
    "DuplicateEventIgnored",
    "EnvelopeMalformedError",
    "EnvelopeMissingError",
    "EphemeralSandbox",
    "EventEnvelope",
    "Finding",
    "FindingSeverity",
    "HarnessPipeline",
    "IdempotencyFilter",
    "JournalEvent",
    "JournalTamperError",
    "KillCategory",
    "KillGate",
    "KillGateInterceptedError",
    "KillInterceptResult",
    "LeaseConflictError",
    "LeaseInfo",
    "LeaseManager",
    "LocalWorker",
    "NegativeDirectiveViolationError",
    "PhysicalWitness",
    "PipelineResult",
    "PipelineStatus",
    "ReviewGate",
    "ReviewRequest",
    "ReviewResponse",
    "RouteDecision",
    "RuleRouter",
    "SandboxExecutionError",
    "SandboxResult",
    "SandboxTimeoutError",
    "TrailingEnvelope",
    "TruthProbe",
    "UnmatchedRouteError",
    "Verdict",
    "WorktreeSandbox",
    "parse_envelope",
    "serialize_envelope",
    "strip_envelope",
]
