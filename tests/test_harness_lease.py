import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.lease import LeaseConflictError, LeaseInfo, LeaseManager


class TestLeaseManager(unittest.TestCase):
    def test_acquire_and_release_lease_normal(self):
        mgr = LeaseManager()
        lease = mgr.acquire_lease(target="repo:codex", worker_id="worker_1", ttl_seconds=60.0)
        self.assertIsInstance(lease, LeaseInfo)
        self.assertEqual(lease.target, "repo:codex")
        self.assertEqual(lease.worker_id, "worker_1")
        self.assertTrue(mgr.is_locked("repo:codex"))

        # Release with correct token
        released = mgr.release_lease("repo:codex", token=lease.token)
        self.assertTrue(released)
        self.assertFalse(mgr.is_locked("repo:codex"))

    def test_concurrent_lease_rejected(self):
        mgr = LeaseManager()
        mgr.acquire_lease(target="repo:codex", worker_id="worker_1", ttl_seconds=60.0)

        # Worker 2 attempting to lock the same entity must be rejected
        with self.assertRaises(LeaseConflictError):
            mgr.acquire_lease(target="repo:codex", worker_id="worker_2", ttl_seconds=60.0)

    def test_expired_lease_auto_reclaimed(self):
        mgr = LeaseManager()
        # Create a short-lived lease of 0.05s
        mgr.acquire_lease(target="repo:codex", worker_id="worker_1", ttl_seconds=0.05)
        self.assertTrue(mgr.is_locked("repo:codex"))

        time.sleep(0.06)
        # Should be recognized as expired and allow worker_2 to acquire
        lease2 = mgr.acquire_lease(target="repo:codex", worker_id="worker_2", ttl_seconds=60.0)
        self.assertEqual(lease2.worker_id, "worker_2")


if __name__ == "__main__":
    unittest.main()
