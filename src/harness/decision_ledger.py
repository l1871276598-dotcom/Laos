import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union


class DecisionType(str, Enum):
    APPROVED_DIRECTIVE = "APPROVED_DIRECTIVE"  # 《定的事》: approved architectural law
    NEGATIVE_DIRECTIVE = "NEGATIVE_DIRECTIVE"  # 《定了不做》: explicitly rejected non-goals


class NegativeDirectiveViolationError(Exception):
    """Raised when an action or proposal violates a previously established negative decision."""
    pass


@dataclass
class DecisionRecord:
    decision_id: str
    decision_type: DecisionType
    topic: str
    rationale: str
    prohibited_patterns: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decided_by: str = "human_author"

    def __post_init__(self):
        if isinstance(self.decision_type, str):
            self.decision_type = DecisionType(self.decision_type)


class DecisionLedger:
    """An immutable, append-only decision ledger storing active directives and negative non-goals."""

    def __init__(self, ledger_path: Union[Path, str]):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def record_decision(self, record: DecisionRecord) -> DecisionRecord:
        line = json.dumps(asdict(record), sort_keys=True, ensure_ascii=False) + "\n"
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return record

    def read_all(self) -> List[DecisionRecord]:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    data = json.loads(stripped)
                    records.append(DecisionRecord(**data))
        return records

    def get_active_directives(self) -> List[DecisionRecord]:
        return [r for r in self.read_all() if r.decision_type == DecisionType.APPROVED_DIRECTIVE]

    def get_negative_directives(self) -> List[DecisionRecord]:
        return [r for r in self.read_all() if r.decision_type == DecisionType.NEGATIVE_DIRECTIVE]

    def is_prohibited(self, proposal_text: str) -> Optional[DecisionRecord]:
        """Checks if proposal_text violates any negative directive patterns."""
        normalized = proposal_text.lower()
        for neg in self.get_negative_directives():
            for pattern in neg.prohibited_patterns:
                pat_cleaned = pattern.strip().lower()
                if not pat_cleaned:
                    continue
                # Word boundary or substring matching
                if re.search(r"\b" + re.escape(pat_cleaned) + r"\b", normalized) or pat_cleaned in normalized:
                    return neg
        return None

    def assert_not_prohibited(self, proposal_text: str) -> None:
        violation = self.is_prohibited(proposal_text)
        if violation is not None:
            raise NegativeDirectiveViolationError(
                f"Negative Directive Violation: Proposal violates immutable decision "
                f"[{violation.decision_id}] on '{violation.topic}': {violation.rationale}"
            )
