import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.probe import TruthProbe
from harness.types import PhysicalWitness, SandboxResult


class TestTruthProbe(unittest.TestCase):
    def test_mint_witness_from_sandbox_result(self):
        probe = TruthProbe()
        sb_res = SandboxResult(
            exit_code=0,
            stdout="Service is running healthy",
            stderr="",
            stdout_sha256="hash_out",
            stderr_sha256="hash_err",
            duration_ms=45,
            environment_fingerprint="env_fp",
        )
        witness = probe.mint_witness_from_sandbox_result(
            pipeline_id="pipe_xyz",
            step_id="STEP5_PROBE",
            sandbox_result=sb_res,
        )
        self.assertIsInstance(witness, PhysicalWitness)
        self.assertEqual(witness.pipeline_id, "pipe_xyz")
        self.assertEqual(witness.step_id, "STEP5_PROBE")
        self.assertEqual(witness.exit_code, 0)
        self.assertTrue(witness.is_valid)
        self.assertEqual(witness.wall_clock_duration_ms, 45)

    def test_execute_local_truth_probe_success(self):
        probe = TruthProbe()
        witness = probe.execute_probe(
            pipeline_id="pipe_test",
            step_id="STEP5",
            probe_command=[sys.executable, "-c", "import sys; sys.exit(0)"],
        )
        self.assertTrue(witness.is_valid)
        self.assertEqual(witness.exit_code, 0)

    def test_execute_local_truth_probe_failure(self):
        probe = TruthProbe()
        witness = probe.execute_probe(
            pipeline_id="pipe_test",
            step_id="STEP5",
            probe_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        self.assertFalse(witness.is_valid)
        self.assertEqual(witness.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
