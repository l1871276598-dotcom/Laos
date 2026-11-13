# -*- coding: utf-8 -*-
"""Unit tests for HealthSentinel (Anti-Entropy Operations)."""

import os
import shutil
import tempfile
import time
import unittest
from harness.dispatch_queue import DispatchQueue
from harness.event_envelope import EventEnvelope
from harness.lease import LeaseManager
from harness.ops.health_sentinel import (
    HealthIssue,
    HealthSentinel,
    HealthStatus,
    SandboxManager,
)


class TestHealthSentinel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sandbox_mgr = SandboxManager(base_dir=self.temp_dir)
        self.lease_mgr = LeaseManager()
        self.dispatch_queue = DispatchQueue()
        self.sentinel = HealthSentinel(
            sandbox_manager=self.sandbox_mgr,
            lease_manager=self.lease_mgr,
            dispatch_queue=self.dispatch_queue,
            orphan_ttl_seconds=0.1,
        )

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_healthy_status_when_no_issues(self):
        status = self.sentinel.scan_and_heal()
        self.assertTrue(status.is_healthy)
        self.assertEqual(status.orphan_sandboxes_cleaned, 0)
        self.assertEqual(status.expired_leases_reclaimed, 0)
        self.assertEqual(status.dead_letters_handled, 0)

    def test_clean_orphan_sandbox(self):
        orphan_dir = os.path.join(self.temp_dir, "orphan_task_123")
        os.makedirs(orphan_dir, exist_ok=True)
        # Set mtime to past
        old_time = time.time() - 100.0
        os.utime(orphan_dir, (old_time, old_time))

        status = self.sentinel.scan_and_heal()
        self.assertTrue(status.is_healthy)
        self.assertEqual(status.orphan_sandboxes_cleaned, 1)
        self.assertFalse(os.path.exists(orphan_dir))

    def test_reclaim_expired_leases(self):
        # Acquire lease with 0.05s TTL
        lease = self.lease_mgr.acquire_lease("entity_1", "worker_old", ttl_seconds=0.05)
        self.assertIsNotNone(lease)
        time.sleep(0.06)

        status = self.sentinel.scan_and_heal()
        self.assertTrue(status.is_healthy)
        self.assertEqual(status.expired_leases_reclaimed, 1)

        # Now new worker can acquire immediately
        new_lease = self.lease_mgr.acquire_lease("entity_1", "worker_new", ttl_seconds=10.0)
        self.assertIsNotNone(new_lease)
        self.assertEqual(new_lease.worker_id, "worker_new")

    def test_handle_stale_dispatch_events(self):
        envelope = EventEnvelope(
            source="test",
            event_type="issue.created",
            target="task_stale",
            payload={"action": "test"},
            dedup_key="dedup_01",
        )
        envelope.retry_count = 10  # Exceeds max retries
        self.dispatch_queue.enqueue(envelope)

        status = self.sentinel.scan_and_heal(max_event_retries=3)
        self.assertTrue(status.is_healthy)
        self.assertEqual(status.dead_letters_handled, 1)
        # Queue should now be empty
        self.assertIsNone(self.dispatch_queue.poll("worker1", timeout=0.01))


if __name__ == "__main__":
    unittest.main()
