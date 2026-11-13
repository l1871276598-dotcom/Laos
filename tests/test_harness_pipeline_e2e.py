import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.journal import AppendOnlyJournal
from harness.pipeline import HarnessPipeline, PipelineResult, PipelineStatus
from harness.review_gate import Finding, ReviewResponse
from harness.types import TrailingEnvelope, Verdict


class TestPipelineE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.journal_path = self.base_path / "journal.jsonl"
        self.snapshots_dir = self.base_path / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.journal = AppendOnlyJournal(self.journal_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_pipeline_success_produces_witness(self):
        pipeline = HarnessPipeline(
            repo_root=REPO_ROOT,
            journal=self.journal,
            pipeline_id="pipe_success_001",
        )

        def mock_reviewer(req):
            return ReviewResponse(
                verdict=Verdict.SHIP,
                findings=[],
                envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
            )

        test_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        probe_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        deployed = False

        def mock_deploy():
            nonlocal deployed
            deployed = True
            return True

        result = pipeline.run(
            reviewer=mock_reviewer,
            diff="--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new",
            test_command=test_cmd,
            deploy_fn=mock_deploy,
            probe_command=probe_cmd,
            require_gate=False,
        )

        self.assertEqual(result.status, PipelineStatus.WITNESS_SEALED)
        self.assertTrue(deployed)
        self.assertGreaterEqual(len(result.witnesses), 2)  # step 2 + step 5 witnesses
        self.assertTrue(all(w.is_valid for w in result.witnesses))

        # Assert events recorded in journal
        events = self.journal.read_all()
        event_types = [e.event_type for e in events]
        self.assertIn("STEP1_REVIEW_PASSED", event_types)
        self.assertIn("STEP2_TESTS_PASSED", event_types)
        self.assertIn("STEP5_PROBE_PASSED", event_types)
        self.assertIn("WITNESS_SEALED", event_types)

    def test_pipeline_aborts_on_step2_test_failure(self):
        pipeline = HarnessPipeline(
            repo_root=REPO_ROOT,
            journal=self.journal,
            pipeline_id="pipe_fail_002",
        )

        def mock_reviewer(req):
            return ReviewResponse(
                verdict=Verdict.SHIP,
                findings=[],
                envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
            )

        # Deliberate failure in Step 2 tests (exit code 1)
        failing_test_cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
        probe_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]

        result = pipeline.run(
            reviewer=mock_reviewer,
            diff="mock diff",
            test_command=failing_test_cmd,
            deploy_fn=lambda: True,
            probe_command=probe_cmd,
        )

        self.assertEqual(result.status, PipelineStatus.ABORTED)
        self.assertIn("STEP2_TESTS_FAILED", [e.event_type for e in self.journal.read_all()])

    def test_suspend_zero_cost_and_resume_flow(self):
        pipeline = HarnessPipeline(
            repo_root=REPO_ROOT,
            journal=self.journal,
            pipeline_id="pipe_suspend_003",
        )

        def mock_reviewer(req):
            return ReviewResponse(
                verdict=Verdict.SHIP,
                envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
            )

        test_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        probe_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]

        # Run with require_gate=True
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
        self.assertIsNotNone(result_suspended.snapshot_path)
        snapshot_file = Path(result_suspended.snapshot_path)
        self.assertTrue(snapshot_file.exists())

        # Verify state snapshot content
        with open(snapshot_file, "r") as f:
            snap_data = json.load(f)
        self.assertEqual(snap_data["pipeline_id"], "pipe_suspend_003")
        self.assertEqual(snap_data["status"], PipelineStatus.SUSPENDED_WAITING_GATE.value)

        # Now simulate resuming from snapshot with approval=True
        deployed_on_resume = False

        def mock_deploy_on_resume():
            nonlocal deployed_on_resume
            deployed_on_resume = True
            return True

        result_resumed = pipeline.resume(
            snapshot_path=snapshot_file,
            approval=True,
            deploy_fn=mock_deploy_on_resume,
            probe_command=probe_cmd,
        )

        self.assertEqual(result_resumed.status, PipelineStatus.WITNESS_SEALED)
        self.assertTrue(deployed_on_resume)
        self.assertIn("PIPELINE_RESUMED", [e.event_type for e in self.journal.read_all()])

    def test_pipeline_triggers_rollback_on_step5_probe_fail(self):
        pipeline = HarnessPipeline(
            repo_root=REPO_ROOT,
            journal=self.journal,
            pipeline_id="pipe_probe_fail_004",
        )

        def mock_reviewer(req):
            return ReviewResponse(
                verdict=Verdict.SHIP,
                envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
            )

        test_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        # Probe fails!
        failing_probe_cmd = [sys.executable, "-c", "import sys; sys.exit(2)"]
        rollback_called = False

        def mock_rollback():
            nonlocal rollback_called
            rollback_called = True

        result = pipeline.run(
            reviewer=mock_reviewer,
            diff="mock diff",
            test_command=test_cmd,
            deploy_fn=lambda: True,
            probe_command=failing_probe_cmd,
            rollback_fn=mock_rollback,
        )

        self.assertEqual(result.status, PipelineStatus.ROLLED_BACK)
        self.assertTrue(rollback_called)
        self.assertIn("STEP5_PROBE_FAILED", [e.event_type for e in self.journal.read_all()])


if __name__ == "__main__":
    unittest.main()
