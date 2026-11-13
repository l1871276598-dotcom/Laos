import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.dispatch_queue import DispatchQueue
from harness.event_envelope import EventEnvelope


class TestDispatchQueue(unittest.TestCase):
    def test_poll_immediate_when_queue_not_empty(self):
        q = DispatchQueue()
        env = EventEnvelope(
            source="manual",
            event_type="test",
            target="repo:codex",
            payload={"msg": "hello"},
            dedup_key="k1",
        )
        q.enqueue(env)
        self.assertEqual(q.qsize(), 1)

        polled = q.poll(worker_id="w1", timeout=1.0)
        self.assertIsNotNone(polled)
        self.assertEqual(polled.event_id, env.event_id)
        self.assertEqual(q.qsize(), 0)

    def test_poll_blocks_until_enqueued(self):
        q = DispatchQueue()
        polled_result = []

        def worker_thread():
            task = q.poll(worker_id="w_block", timeout=2.0)
            polled_result.append(task)

        t = threading.Thread(target=worker_thread)
        t.start()

        time.sleep(0.05)
        self.assertEqual(len(polled_result), 0)  # Still waiting

        env = EventEnvelope(
            source="manual",
            event_type="test",
            target="repo:codex",
            payload={},
            dedup_key="k2",
        )
        q.enqueue(env)
        t.join(timeout=1.0)

        self.assertEqual(len(polled_result), 1)
        self.assertIsNotNone(polled_result[0])
        self.assertEqual(polled_result[0].event_id, env.event_id)

    def test_poll_timeout_returns_none(self):
        q = DispatchQueue()
        start = time.monotonic()
        polled = q.poll(worker_id="w1", timeout=0.05)
        duration = time.monotonic() - start
        self.assertIsNone(polled)
        self.assertGreaterEqual(duration, 0.04)

    def test_ack_and_nack_requeue(self):
        q = DispatchQueue()
        env = EventEnvelope(
            source="manual",
            event_type="test",
            target="repo:codex",
            payload={},
            dedup_key="k3",
        )
        q.enqueue(env)
        task = q.poll(worker_id="w1", timeout=0.5)

        # NACK with requeue
        q.nack(task.event_id, requeue=True)
        self.assertEqual(q.qsize(), 1)

        task2 = q.poll(worker_id="w2", timeout=0.5)
        self.assertEqual(task2.event_id, env.event_id)

        # ACK closes task
        q.ack(task2.event_id)
        self.assertEqual(q.qsize(), 0)


if __name__ == "__main__":
    unittest.main()
