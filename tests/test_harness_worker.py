import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.dispatch_queue import DispatchQueue
from harness.event_envelope import EventEnvelope
from harness.lease import LeaseConflictError, LeaseManager
from harness.router import RuleRouter
from harness.worker import LocalWorker


class TestLocalWorker(unittest.TestCase):
    def setUp(self):
        self.queue = DispatchQueue()
        self.router = RuleRouter({
            "rules": [
                {
                    "rule_id": "r1",
                    "match": {"source": "git", "event_type": "push"},
                    "target_host": "local",
                    "agent_adapter": "codex",
                    "procedure_id": "p1",
                }
            ]
        })
        self.lease_mgr = LeaseManager()

    def test_worker_polls_and_invokes_pipeline(self):
        invocations = []

        def mock_executor(task, route):
            invocations.append((task.event_id, route.rule_id))
            return "SUCCESS"

        worker = LocalWorker(
            worker_id="mac_w1",
            queue=self.queue,
            router=self.router,
            lease_mgr=self.lease_mgr,
            pipeline_executor=mock_executor,
        )

        env = EventEnvelope(
            source="git",
            event_type="push",
            target="repo:codex",
            payload={"commit": "abc"},
            dedup_key="d1",
        )
        self.queue.enqueue(env)

        res = worker.poll_and_execute_once(timeout=0.1)
        self.assertEqual(res, "SUCCESS")
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0], (env.event_id, "r1"))

        # Lease must be released after completion
        self.assertFalse(self.lease_mgr.is_locked("repo:codex"))
        # Task must be ACKed and queue empty
        self.assertEqual(self.queue.qsize(), 0)

    def test_worker_lease_conflict_requeues_task(self):
        # Manually lock repo:codex by another worker
        self.lease_mgr.acquire_lease("repo:codex", worker_id="other_worker", ttl_seconds=60.0)

        worker = LocalWorker(
            worker_id="mac_w1",
            queue=self.queue,
            router=self.router,
            lease_mgr=self.lease_mgr,
            pipeline_executor=lambda t, r: "SHOULD_NOT_RUN",
        )

        env = EventEnvelope(
            source="git",
            event_type="push",
            target="repo:codex",
            payload={},
            dedup_key="d2",
        )
        self.queue.enqueue(env)

        with self.assertRaises(LeaseConflictError):
            worker.poll_and_execute_once(timeout=0.1)

        # Task should have been NACKed back into queue for retry
        self.assertEqual(self.queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
