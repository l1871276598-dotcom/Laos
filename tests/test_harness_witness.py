import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.types import PhysicalWitness


class TestPhysicalWitness(unittest.TestCase):
    def test_witness_integrity_and_hash_calculation(self):
        w = PhysicalWitness(
            pipeline_id="pipe_001",
            step_id="STEP2",
            exit_code=0,
            stdout_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            stderr_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            wall_clock_duration_ms=120,
            environment_fingerprint="env_hash_123",
            is_valid=True,
        )
        digest = w.compute_witness_digest()
        self.assertEqual(len(digest), 64)
        self.assertTrue(w.is_valid)

    def test_witness_invalid_if_exit_code_nonzero(self):
        w = PhysicalWitness(
            pipeline_id="pipe_001",
            step_id="STEP2",
            exit_code=1,
            stdout_sha256="abc",
            stderr_sha256="def",
            wall_clock_duration_ms=50,
            environment_fingerprint="env",
            is_valid=False,
        )
        self.assertFalse(w.is_valid)


if __name__ == "__main__":
    unittest.main()
