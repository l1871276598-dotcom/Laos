import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.dispatch_queue import DispatchQueue
from harness.event_envelope import (
    DuplicateEventIgnored,
    EventEnvelope,
    IdempotencyFilter,
)
from harness.journal import AppendOnlyJournal
from harness.lease import LeaseManager
from harness.pipeline import HarnessPipeline, PipelineStatus
from harness.review_gate import ReviewResponse
from harness.router import RuleRouter
from harness.types import TrailingEnvelope, Verdict
from harness.worker import LocalWorker


class TestSlice2E2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.journal_path = self.base_dir / "journal.jsonl"
        self.journal = AppendOnlyJournal(self.journal_path)

        self.queue = DispatchQueue()
        self.idempotency = IdempotencyFilter()
        self.lease_mgr = LeaseManager()
        self.router = RuleRouter({
            "rules": [
                {
                    "rule_id": "rule_gh_pr",
                    "match": {"source": "github_webhook", "event_type": "pull_request"},
                    "target_host": "local-mac",
                    "agent_adapter": "codex_cli",
                    "procedure_id": "proc_code_review_v1",
                    "token_budget": 50000,
                    "require_gate": False,
                }
            ]
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_slice1_and_slice2_e2e_closed_loop(self):
        # 1. External event submitted
        env = EventEnvelope(
            source="github_webhook",
            event_type="pull_request",
            target="repo:codex",
            payload={"pr_id": 99, "diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b"},
            dedup_key="pr-99-v1",
        )

        # Idempotency filter checks and records
        self.assertTrue(self.idempotency.check_and_record(env))
        self.queue.enqueue(env)

        # Duplicate event should be blocked
        with self.assertRaises(DuplicateEventIgnored):
            self.idempotency.check_and_record(env)

        # 2. Worker executes Slice 1 HarnessPipeline
        def pipeline_executor(task, route):
            pipeline = HarnessPipeline(
                repo_root=REPO_ROOT,
                journal=self.journal,
                pipeline_id=f"pipe_{task.event_id[:8]}",
            )

            def mock_reviewer(req):
                return ReviewResponse(
                    verdict=Verdict.SHIP,
                    envelope=TrailingEnvelope(verdict=Verdict.SHIP, ttl=req.ttl - 1),
                )

            test_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
            probe_cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]

            return pipeline.run(
                reviewer=mock_reviewer,
                diff=task.payload.get("diff", ""),
                test_command=test_cmd,
                deploy_fn=lambda: True,
                probe_command=probe_cmd,
                require_gate=route.require_gate,
            )

        worker = LocalWorker(
            worker_id="worker_mac_local",
            queue=self.queue,
            router=self.router,
            lease_mgr=self.lease_mgr,
            pipeline_executor=pipeline_executor,
        )

        result = worker.poll_and_execute_once(timeout=0.2)

        # 3. Verify physical witness sealed & pipeline success
        self.assertIsNotNone(result)
        self.assertEqual(result.status, PipelineStatus.WITNESS_SEALED)
        self.assertEqual(len(result.witnesses), 2)
        self.assertTrue(all(w.is_valid for w in result.witnesses))

        # 4. Verify post-execution states
        self.assertEqual(self.queue.qsize(), 0)
        self.assertFalse(self.lease_mgr.is_locked("repo:codex"))

        # 5. Verify journal records
        events = self.journal.read_all()
        event_types = [e.event_type for e in events]
        self.assertIn("STEP1_REVIEW_PASSED", event_types)
        self.assertIn("STEP2_TESTS_PASSED", event_types)
        self.assertIn("STEP5_PROBE_PASSED", event_types)
        self.assertIn("WITNESS_SEALED", event_types)


if __name__ == "__main__":
    unittest.main()
