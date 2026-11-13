import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.kill_gate import (
    ActionProposal,
    KillCategory,
    KillGate,
    KillGateInterceptedError,
)


class TestKillGate(unittest.TestCase):
    def setUp(self):
        self.gate = KillGate()

    def test_safe_action_passes(self):
        proposal = ActionProposal(
            action_type="RUN_TEST",
            description="Run unit test suite in sandbox",
            target="repo:codex",
        )
        res = self.gate.check(proposal)
        self.assertFalse(res.is_intercepted)
        self.gate.assert_safe_to_execute(proposal)

    def test_delete_production_data_intercepted(self):
        proposal = ActionProposal(
            action_type="DROP_DATABASE",
            description="Drop production sqlite database table",
            target="db:sessions.sqlite",
            category=KillCategory.DELETE_PRODUCTION_DATA,
        )
        res = self.gate.check(proposal)
        self.assertTrue(res.is_intercepted)
        self.assertEqual(res.category, KillCategory.DELETE_PRODUCTION_DATA)

        with self.assertRaises(KillGateInterceptedError):
            self.gate.assert_safe_to_execute(proposal)

    def test_mutate_credentials_intercepted(self):
        proposal = ActionProposal(
            action_type="ROTATE_KEY",
            description="Update API secret keys in config",
            target="config/auth.json",
        )
        res = self.gate.check(proposal)
        self.assertTrue(res.is_intercepted)
        self.assertEqual(res.category, KillCategory.MUTATE_CREDENTIALS)

    def test_all_seven_categories_recognized(self):
        categories = list(KillCategory)
        self.assertEqual(len(categories), 7)


if __name__ == "__main__":
    unittest.main()
