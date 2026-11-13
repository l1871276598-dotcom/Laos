# -*- coding: utf-8 -*-
"""Unit tests for FeishuChannel (Interactive Message Card Delivery & Callback)."""

import tempfile
import unittest
from harness.adapters.feishu_channel import ApprovalAction, FeishuCardBuilder, FeishuChannel
from harness.approval_card import ApprovalCard
from harness.decision_ledger import DecisionLedger
from harness.kill_gate import KillCategory


class TestFeishuChannel(unittest.TestCase):
    def test_build_feishu_interactive_card(self):
        card = ApprovalCard(
            pipeline_id="prop-001",
            title="请求核准生产数据库迁移",
            event_source="agent_proposal",
            action_summary="将用户表切往新集群",
            recommendation="REJECT",
            rationale="容量扩容需要",
            affected_entities=["/data/mysql/prod_users"],
            risk_category=KillCategory.DELETE_PRODUCTION_DATA.value,
        )

        builder = FeishuCardBuilder()
        payload = builder.build_card_payload(card)

        self.assertEqual(payload["msg_type"], "interactive")
        self.assertIn("card", payload)
        card_content = payload["card"]
        # Check header
        self.assertEqual(card_content["header"]["template"], "red")  # High risk DATA_DELETION
        self.assertIn("生产数据库迁移", card_content["header"]["title"]["content"])

        # Check elements
        elements = card_content["elements"]
        self.assertTrue(any(elem.get("tag") == "markdown" and "将用户表切往新集群" in elem.get("content", "") for elem in elements))
        self.assertTrue(any(elem.get("tag") == "markdown" and "DELETE_PRODUCTION_DATA" in elem.get("content", "") for elem in elements))

        # Check action buttons
        action_elements = [elem for elem in elements if elem.get("tag") == "action"]
        self.assertEqual(len(action_elements), 1)
        actions = action_elements[0]["actions"]
        self.assertEqual(len(actions), 3)

        btn_approve = actions[0]
        self.assertEqual(btn_approve["type"], "primary")
        self.assertEqual(btn_approve["value"]["action"], "APPROVE")
        self.assertEqual(btn_approve["value"]["proposal_id"], "prop-001")

        btn_reject = actions[1]
        self.assertEqual(btn_reject["type"], "danger")
        self.assertEqual(btn_reject["value"]["action"], "REJECT")

        btn_negative = actions[2]
        self.assertEqual(btn_negative["value"]["action"], "ADD_TO_NEGATIVE_LEDGER")

    def test_send_approval_card_dry_run(self):
        channel = FeishuChannel(dry_run=True)
        card = ApprovalCard(
            pipeline_id="prop-002",
            title="常规发布核准",
            event_source="ci_bot",
            action_summary="发布 v1.0.1",
            recommendation="APPROVE",
            rationale="Bugfix release",
        )

        res = channel.send_approval_card(card)
        self.assertEqual(res["status"], "dry_run_success")
        self.assertIn("payload", res)
        self.assertEqual(res["payload"]["msg_type"], "interactive")

    def test_handle_callback_and_ledger_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as f_ledger:
            ledger = DecisionLedger(f_ledger.name)
            channel = FeishuChannel(dry_run=True)

            # Simulate user clicking "加入《定了不做》" button in Feishu card
            callback_payload = {
                "action": {
                    "value": {
                        "action": "ADD_TO_NEGATIVE_LEDGER",
                        "proposal_id": "prop-forbid-01",
                        "proposal_summary": "Do not delete active branches",
                        "reason": "Forbidden by project governance",
                    }
                },
                "open_id": "ou_user123",
                "open_message_id": "om_card456",
            }

            action_name, record = channel.handle_callback(callback_payload, ledger=ledger)
            self.assertEqual(action_name, "ADD_TO_NEGATIVE_LEDGER")
            self.assertIsNotNone(record)

            # Verify that ledger permanently blocked this proposal
            blocked_record = ledger.is_prohibited("Do not delete active branches")
            self.assertIsNotNone(blocked_record)
            self.assertEqual(blocked_record.topic, "Do not delete active branches")

    def test_sign_verification(self):
        channel = FeishuChannel(secret="test_secret_key", dry_run=True)
        timestamp = 1700000000
        signature = channel.calculate_signature(timestamp, "test_secret_key")
        self.assertTrue(isinstance(signature, str))
        self.assertGreater(len(signature), 10)


if __name__ == "__main__":
    unittest.main()
