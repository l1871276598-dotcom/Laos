import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.approval_card import ApprovalCard
from harness.kill_gate import KillCategory


class TestApprovalCard(unittest.TestCase):
    def test_approval_card_markdown_rendering(self):
        card = ApprovalCard(
            pipeline_id="pipe_100",
            title="Production Database Migration Request",
            event_source="github_webhook",
            risk_category=KillCategory.DELETE_PRODUCTION_DATA.value,
            action_summary="Drop table old_records and prune audit index",
            affected_entities=["db:sessions.sqlite"],
            recommendation="REJECT",
            rationale="Dropping tables violates immutable provenance invariant.",
        )

        md = card.to_markdown()
        self.assertIn("# 🚨 [LAOS Human Gate] Production Database Migration Request", md)
        self.assertIn("pipe_100", md)
        self.assertIn("DELETE_PRODUCTION_DATA", md)
        self.assertIn("db:sessions.sqlite", md)
        self.assertIn("**推荐裁决**: REJECT", md)
        self.assertIn("[1] 批准 (Approve)", md)
        self.assertIn("[2] 拒绝 (Reject)", md)

    def test_approval_card_json_dict(self):
        card = ApprovalCard(
            pipeline_id="pipe_200",
            title="Deploy release v0.14.0",
            event_source="cron",
            risk_category=None,
            action_summary="Deploy new version to staging",
            affected_entities=["service:gateway"],
            recommendation="APPROVE",
            rationale="All 1262 unit tests passed with valid physical witness.",
        )
        d = card.to_dict()
        self.assertEqual(d["pipeline_id"], "pipe_200")
        self.assertEqual(d["recommendation"], "APPROVE")
        self.assertIsNone(d["risk_category"])


if __name__ == "__main__":
    unittest.main()
