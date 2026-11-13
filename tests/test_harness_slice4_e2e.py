# -*- coding: utf-8 -*-
"""End-to-end integration tests for LAOS Harness Slice 4 (Operations, Recovery & Delivery)."""

import os
import shutil
import tempfile
import unittest
from harness.adapters.feishu_channel import ApprovalAction, FeishuChannel
from harness.approval_card import ApprovalCard
from harness.decision_ledger import DecisionLedger
from harness.kill_gate import ActionProposal, KillCategory, KillGate
from harness.lease import LeaseManager
from harness.ops.cross_model_recovery import (
    JournalEntry,
    PipelineJournal,
    StepName,
    build_recovery_packet,
    render_bounded_prompt_projection,
    validate_recovery_packet,
)
from harness.ops.health_sentinel import HealthSentinel, SandboxManager
from harness.types import Verdict


class TestSlice4EndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sandbox_mgr = SandboxManager(base_dir=self.temp_dir)
        self.lease_mgr = LeaseManager()
        self.ledger_file = os.path.join(self.temp_dir, "ledger.jsonl")
        self.journal_file = os.path.join(self.temp_dir, "journal.jsonl")
        self.ledger = DecisionLedger(self.ledger_file)
        self.journal = PipelineJournal(self.journal_file)
        self.sentinel = HealthSentinel(
            sandbox_manager=self.sandbox_mgr,
            lease_manager=self.lease_mgr,
            orphan_ttl_seconds=0.1,
        )

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_approval_handoff_and_anti_entropy_loop(self):
        # 1. Gate intercepts high-risk proposal
        gate = KillGate()
        proposal = ActionProposal(
            action_type="service_restart",
            description="Emergency restart request for laos_core",
            target="systemctl restart laos_core",
        )
        intercept_res = gate.check(proposal)
        self.assertTrue(intercept_res.is_intercepted)
        self.assertEqual(intercept_res.category, KillCategory.RESTART_CORE_SERVICE)

        # 2. Render approval card and deliver via Feishu channel
        card = ApprovalCard(
            pipeline_id="prop-core-restart-01",
            title="请求核准重启 LAOS 核心服务",
            event_source="sentinel_auto_watch",
            action_summary="执行 systemctl restart laos_core",
            recommendation="REJECT",
            rationale="内存突刺排查自愈",
            risk_category=intercept_res.category.value,
            affected_entities=["/etc/systemd/system/laos_core.service"],
        )

        feishu = FeishuChannel(dry_run=True)
        res = feishu.send_approval_card(card)
        self.assertEqual(res["status"], "dry_run_success")

        # 3. Simulate human approving the card via callback
        callback_payload = {
            "action": {
                "value": {
                    "action": "APPROVE",
                    "proposal_id": "prop-core-restart-01",
                    "proposal_summary": "Allow restart of laos_core service",
                }
            },
            "open_id": "ou_admin",
        }
        action_name, record = feishu.handle_callback(callback_payload, ledger=self.ledger)
        self.assertEqual(action_name, "APPROVE")
        self.assertIsNotNone(record)
        active_topics = [r.topic for r in self.ledger.get_active_directives()]
        self.assertIn("Allow restart of laos_core service", active_topics)

        # 4. Pipeline journal records successful recovery execution
        self.journal.record(JournalEntry(
            step=StepName.STEP5_GROUND_TRUTH_PROBE,
            verdict=Verdict.SHIP,
            evidence_hash="sha256:1122334455667788",
            why="Service restarted and health probe verified live",
        ))

        # 5. Export Cross-Model Recovery packet
        packet = build_recovery_packet(
            context_id="laos-e2e-handoff-01",
            task_name="Service Restart & Maintenance",
            breakpoint="service-restart-verified",
            anchor_commit="4af0820",
            ledger=self.ledger,
            journal=self.journal,
            single_next_command="python3 -m unittest",
        )

        self.assertIn("Allow restart of laos_core service", packet.active_directives)
        self.assertEqual(packet.source_anchor_commit, "4af0820")

        # Validate packet
        valid, errors = validate_recovery_packet(packet, current_commit="4af0820")
        self.assertTrue(valid)
        self.assertEqual(errors, [])

        # Render bounded prompt projection for Claude
        prompt = render_bounded_prompt_projection(packet, target_model="claude")
        self.assertIn("TARGET_MODEL: CLAUDE", prompt)
        self.assertIn("service-restart-verified", prompt)

        # 6. Anti-Entropy Health Sentinel sweeps system
        status = self.sentinel.scan_and_heal()
        self.assertTrue(status.is_healthy)


if __name__ == "__main__":
    unittest.main()
