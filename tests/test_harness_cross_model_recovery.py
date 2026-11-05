# -*- coding: utf-8 -*-
"""Unit tests for CrossModelRecovery (Cross-Model Context Handoff & Projection)."""

import tempfile
import unittest
from harness.decision_ledger import DecisionLedger, DecisionRecord, DecisionType
from harness.ops.cross_model_recovery import (
    JournalEntry,
    PipelineJournal,
    RecoveryPacket,
    StepName,
    build_recovery_packet,
    render_bounded_prompt_projection,
    validate_recovery_packet,
)
from harness.types import Verdict


class TestCrossModelRecovery(unittest.TestCase):
    def test_packet_creation_and_dict_roundtrip(self):
        packet = RecoveryPacket(
            context_id="laos-task-101",
            task_name="Harness Slice 4 Delivery",
            current_breakpoint="slice4-tdd-pending",
            source_anchor_commit="4af0820",
            active_worktree_clean=True,
            verified_evidence_hashes=[{"path": "Current State.md", "sha256": "abc1234"}],
            completed_slices=["Slice 1: PASS", "Slice 2: PASS", "Slice 3: PASS"],
            single_next_command="python3 -m unittest discover",
            unresolved_blockers=[],
            unauthorized_action_rate=0.0,
            citations=[{"field": "completed_slices", "locator": "plan#L40"}],
            negative_directives=["Do NOT add third-party network dependencies"],
            active_directives=["Keep LOC minimal"],
        )

        d = packet.to_dict()
        restored = RecoveryPacket.from_dict(d)
        self.assertEqual(restored.context_id, "laos-task-101")
        self.assertEqual(restored.source_anchor_commit, "4af0820")
        self.assertEqual(restored.negative_directives, ["Do NOT add third-party network dependencies"])
        self.assertEqual(restored.unauthorized_action_rate, 0.0)

    def test_yaml_serialization_stdlib_roundtrip(self):
        packet = RecoveryPacket(
            context_id="laos-yaml-test",
            task_name="YAML stdlib test",
            current_breakpoint="test-breakpoint",
            source_anchor_commit="1234567",
            active_worktree_clean=True,
            verified_evidence_hashes=[{"path": "foo.py", "sha256": "hash999"}],
            completed_slices=["Slice 1"],
            single_next_command="pytest",
            unresolved_blockers=["No blocker"],
            unauthorized_action_rate=0.0,
            citations=[],
            negative_directives=["Never ask twice"],
            active_directives=["Ship it"],
        )

        yaml_text = packet.to_yaml()
        self.assertIn("context_id: laos-yaml-test", yaml_text)
        self.assertIn("source_anchor_commit: '1234567'", yaml_text)
        self.assertIn("negative_directives:", yaml_text)

        loaded = RecoveryPacket.from_yaml(yaml_text)
        self.assertEqual(loaded.context_id, packet.context_id)
        self.assertEqual(loaded.source_anchor_commit, packet.source_anchor_commit)
        self.assertEqual(loaded.negative_directives, packet.negative_directives)

    def test_build_recovery_packet_from_ledger_and_journal(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as f_ledger, \
             tempfile.NamedTemporaryFile(suffix=".jsonl") as f_journal:
            ledger = DecisionLedger(f_ledger.name)
            ledger.record_decision(
                DecisionRecord(
                    decision_id="neg_01",
                    decision_type=DecisionType.NEGATIVE_DIRECTIVE,
                    topic="Use requests library",
                    rationale="Violation of standard library purity invariant",
                    prohibited_patterns=["requests.get"],
                )
            )
            ledger.record_decision(
                DecisionRecord(
                    decision_id="dir_01",
                    decision_type=DecisionType.APPROVED_DIRECTIVE,
                    topic="Use urllib.request only",
                    rationale="Stdlib purity",
                )
            )

            journal = PipelineJournal(f_journal.name)
            journal.record(JournalEntry(
                step=StepName.STEP2_TRANSIENT_VERIFY,
                verdict=Verdict.SHIP,
                evidence_hash="sha256:fedcba9876543210",
                why="Tests passed",
            ))

            packet = build_recovery_packet(
                context_id="ctx-recovery-auto",
                task_name="Auto handoff",
                breakpoint="breakpoint-step2-done",
                anchor_commit="4af0820",
                ledger=ledger,
                journal=journal,
                single_next_command="git status",
            )

            self.assertEqual(len(packet.negative_directives), 1)
            self.assertIn("Use requests library", packet.negative_directives[0])
            self.assertEqual(len(packet.active_directives), 1)
            self.assertEqual(packet.active_directives[0], "Use urllib.request only")
            self.assertTrue(any(e["sha256"] == "sha256:fedcba9876543210" for e in packet.verified_evidence_hashes))

    def test_render_bounded_prompt_projection(self):
        packet = RecoveryPacket(
            context_id="laos-prompt-001",
            task_name="Handoff to Claude",
            current_breakpoint="slice4-ready",
            source_anchor_commit="4af0820",
            active_worktree_clean=True,
            verified_evidence_hashes=[],
            completed_slices=["Slice 1", "Slice 2", "Slice 3"],
            single_next_command="python3 -m unittest",
            unresolved_blockers=[],
            unauthorized_action_rate=0.0,
            citations=[],
            negative_directives=["Never re-introduce third party libraries"],
            active_directives=["Continue Slice 4 implementation"],
        )

        prompt = render_bounded_prompt_projection(packet, target_model="claude")
        self.assertIn("BOUNDED CONTEXT PROJECTION (HANDOFF PROTOCOL)", prompt)
        self.assertIn("TARGET_MODEL: CLAUDE", prompt)
        self.assertIn("ANCHOR_COMMIT: 4af0820", prompt)
        self.assertIn("BREAKPOINT: slice4-ready", prompt)
        self.assertIn("NEXT_COMMAND: python3 -m unittest", prompt)
        self.assertIn("Never re-introduce third party libraries", prompt)

    def test_validate_recovery_packet(self):
        packet = RecoveryPacket(
            context_id="ctx-valid",
            task_name="Validation test",
            current_breakpoint="bp-ok",
            source_anchor_commit="commit_aaa",
            active_worktree_clean=True,
            verified_evidence_hashes=[],
            completed_slices=[],
            single_next_command="echo ok",
            unresolved_blockers=[],
            unauthorized_action_rate=0.0,
            citations=[],
            negative_directives=[],
            active_directives=[],
        )

        # Valid case
        is_valid, errors = validate_recovery_packet(packet, current_commit="commit_aaa")
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

        # Anchor commit mismatch (stale/drift)
        is_valid, errors = validate_recovery_packet(packet, current_commit="commit_bbb")
        self.assertFalse(is_valid)
        self.assertTrue(any("Anchor commit mismatch" in e for e in errors))

        # Unauthorized action rate > 0
        packet.unauthorized_action_rate = 0.05
        is_valid, errors = validate_recovery_packet(packet, current_commit="commit_aaa")
        self.assertFalse(is_valid)
        self.assertTrue(any("Unauthorized action rate" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
