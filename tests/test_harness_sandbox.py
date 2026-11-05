import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.sandbox import (
    EphemeralSandbox,
    SandboxExecutionError,
    SandboxTimeoutError,
    WorktreeSandbox,
)
from harness.types import SandboxResult


class TestEphemeralSandbox(unittest.TestCase):
    def test_sandbox_creates_isolated_tempdir(self):
        with EphemeralSandbox() as sb:
            self.assertTrue(sb.path.exists())
            self.assertTrue(sb.path.is_dir())
            self.assertNotEqual(sb.path.resolve(), REPO_ROOT.resolve())
            sandbox_path = sb.path
        # Cleanup guarantee: directory should be deleted after context exit
        self.assertFalse(sandbox_path.exists())

    def test_sandbox_executes_command_and_captures_exit_code(self):
        with EphemeralSandbox() as sb:
            # 1. Success command
            res_ok = sb.run_command([sys.executable, "-c", "import sys; sys.stdout.write('test-stdout'); sys.exit(0)"])
            self.assertIsInstance(res_ok, SandboxResult)
            self.assertEqual(res_ok.exit_code, 0)
            self.assertEqual(res_ok.stdout, "test-stdout")
            self.assertTrue(len(res_ok.stdout_sha256) == 64)
            self.assertGreaterEqual(res_ok.duration_ms, 0)

            # 2. Failure command
            res_fail = sb.run_command([sys.executable, "-c", "import sys; sys.stderr.write('err-out'); sys.exit(42)"])
            self.assertEqual(res_fail.exit_code, 42)
            self.assertEqual(res_fail.stderr, "err-out")
            self.assertTrue(len(res_fail.stderr_sha256) == 64)

    def test_sandbox_cleanup_on_exception(self):
        sandbox_path = None
        with self.assertRaises(RuntimeError):
            with EphemeralSandbox() as sb:
                sandbox_path = sb.path
                self.assertTrue(sandbox_path.exists())
                raise RuntimeError("Deliberate failure inside sandbox")
        # Ensure cleanup happened despite the exception
        self.assertIsNotNone(sandbox_path)
        self.assertFalse(sandbox_path.exists())

    def test_sandbox_timeout_handling(self):
        with EphemeralSandbox() as sb:
            with self.assertRaises(SandboxTimeoutError):
                sb.run_command([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.1)

    def test_worktree_sandbox_lifecycle(self):
        # Creates an ephemeral detached git worktree
        with WorktreeSandbox(repo_root=REPO_ROOT, commit_or_branch="HEAD") as wsb:
            self.assertTrue(wsb.path.exists())
            self.assertTrue((wsb.path / ".git").exists())
            res = wsb.run_command(["git", "status", "--porcelain"])
            self.assertEqual(res.exit_code, 0)
            worktree_path = wsb.path

        # After exit, worktree should be pruned and directory should not exist
        self.assertFalse(worktree_path.exists())


if __name__ == "__main__":
    unittest.main()
