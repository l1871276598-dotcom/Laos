import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.decision_ledger import (
    DecisionLedger,
    DecisionRecord,
    DecisionType,
    NegativeDirectiveViolationError,
)


class TestDecisionLedger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger_file = Path(self.temp_dir.name) / "decisions.jsonl"
        self.ledger = DecisionLedger(self.ledger_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_retrieve_directives(self):
        d1 = DecisionRecord(
            decision_id="decision-20261105-use-sqlite",
            decision_type=DecisionType.APPROVED_DIRECTIVE,
            topic="Persistence",
            rationale="Use local SQLite rather than Postgres",
        )
        self.ledger.record_decision(d1)

        active = self.ledger.get_active_directives()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].decision_id, "decision-20261105-use-sqlite")

    def test_negative_directive_blocks_proposal(self):
        # Human previously rejected introducing Redis: "定了不做"
        d_neg = DecisionRecord(
            decision_id="decision-20261105-no-redis",
            decision_type=DecisionType.NEGATIVE_DIRECTIVE,
            topic="Caching",
            rationale="Do not introduce Redis dependency",
            prohibited_patterns=["redis", "redis-py", "redis://"],
        )
        self.ledger.record_decision(d_neg)

        # Agent proposes introducing Redis -> must be blocked
        violation = self.ledger.is_prohibited("Let's add redis-py for caching")
        self.assertIsNotNone(violation)
        self.assertEqual(violation.decision_id, "decision-20261105-no-redis")

        with self.assertRaises(NegativeDirectiveViolationError):
            self.ledger.assert_not_prohibited("Install redis service on port 6379")

    def test_unrelated_proposal_passes(self):
        d_neg = DecisionRecord(
            decision_id="decision-20261105-no-redis",
            decision_type=DecisionType.NEGATIVE_DIRECTIVE,
            topic="Caching",
            rationale="Do not introduce Redis",
            prohibited_patterns=["redis"],
        )
        self.ledger.record_decision(d_neg)

        # Normal proposal should pass
        self.assertIsNone(self.ledger.is_prohibited("Refactor SQLite connection pool"))
        self.ledger.assert_not_prohibited("Refactor SQLite connection pool")


if __name__ == "__main__":
    unittest.main()
