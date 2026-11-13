import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.approval_card import ApprovalCard
from harness.decision_ledger import (
    DecisionLedger,
    DecisionRecord,
    DecisionType,
    NegativeDirectiveViolationError,
)
from harness.journal import AppendOnlyJournal
from harness.kill_gate import ActionProposal, KillCategory, KillGate
from harness.pipeline import HarnessPipeline, PipelineStatus
from harness.review_gate import ReviewResponse
from harness.types import TrailingEnvelope, Verdict


class TestSlice3E2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.journal = AppendOnlyJournal(self.base_dir / "journal.jsonl")
        self.ledger = DecisionLedger(self.base_dir / "decisions.jsonl")
        self.snapshots_dir = self.base_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.kill_gate = KillGate()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_kill_gate_intercepts_and_generates_approval_card(self):
        # 1. Action proposal with sensitive deletion
        proposal = ActionProposal(
            action_type="PURGE_DATABASE",
            description="Purge old audit logs from production database",
            target="db:sessions.sqlite",
        )
        intercept = self.kill_gate.check(proposal)
        self.assertTrue(intercept.is_intercepted)
        self.assertEqual(intercept.category, KillCategory.DELETE_PRODUCTION_DATA)

        # 2. Generate human approval card
        card = ApprovalCard(
            pipeline_id="pipe_sensitive_01",
            title="Database Purge Authorization",
            event_source="cron",
            risk_category=intercept.category.value,
            action_summary=proposal.description,
            affected_entities=[proposal.target],
            recommendation="REJECT",
            rationale="Production audit log purges must preserve provenance.",
        )
        self.assertIn("pipe_sensitive_01", card.to_markdown())

        # 3. Simulate human rejecting: records as NEGATIVE_DIRECTIVE ("定了不做")
        neg_record = DecisionRecord(
            decision_id="decision-20261105-no-purge-audit-logs",
            decision_type=DecisionType.NEGATIVE_DIRECTIVE,
            topic="Audit Log Lifecycle",
            rationale=card.rationale,
            prohibited_patterns=["purge old audit logs", "purge_database"],
        )
        self.ledger.record_decision(neg_record)

        # 4. "永不问第二遍" Invariant: Future attempts to propose the same action are immediately blocked
        with self.assertRaises(NegativeDirectiveViolationError):
            self.ledger.assert_not_prohibited("Attempting to purge old audit logs via cron")

    def test_human_approval_promotes_directive_and_resumes_pipeline(self):
        # Pipeline runs and suspends at human gate
        pipeline = HarnessPipeline(
            repo_root=REPO_ROOT,
            journal=self.journal,
            pipeline_id="pipe_gate_resume_02",
        )

        def mock_reviewer(req):
            return ReviewResponse(
                verdict=Verdict.SHIP,
                envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
            )

        test_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        probe_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]

        # Run with require_gate=True (Suspend-Zero-Cost)
        result_suspended = pipeline.run(
            reviewer=mock_reviewer,
            diff="mock diff",
            test_command=test_cmd,
            deploy_fn=lambda: True,
            probe_command=probe_cmd,
            require_gate=True,
            snapshot_dir=self.snapshots_dir,
        )
        self.assertEqual(result_suspended.status, PipelineStatus.SUSPENDED_WAITING_GATE)

        # Human approves -> records APPROVED_DIRECTIVE ("定的事")
        approved_directive = DecisionRecord(
            decision_id="decision-20261105-approve-deploy",
            decision_type=DecisionType.APPROVED_DIRECTIVE,
            topic="Deployment Authorization",
            rationale="Verified by 1262 automated unit tests.",
        )
        self.ledger.record_decision(approved_directive)

        # Resume pipeline using saved snapshot
        snapshot_file = Path(result_suspended.snapshot_path)
        result_resumed = pipeline.resume(
            snapshot_path=snapshot_file,
            approval=True,
            deploy_fn=lambda: True,
            probe_command=probe_cmd,
        )

        self.assertEqual(result_resumed.status, PipelineStatus.WITNESS_SEALED)
        self.assertEqual(len(self.ledger.get_active_directives()), 1)


if __name__ == "__main__":
    unittest.main()
