import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.event_envelope import (
    DuplicateEventIgnored,
    EventEnvelope,
    IdempotencyFilter,
)


class TestEventEnvelope(unittest.TestCase):
    def test_envelope_dedup_hash_deterministic(self):
        env1 = EventEnvelope(
            source="github_webhook",
            event_type="pull_request",
            target="repo:codex",
            payload={"pr_number": 42},
            dedup_key="pr-42-commit-abc",
        )
        env2 = EventEnvelope(
            source="github_webhook",
            event_type="pull_request",
            target="repo:codex",
            payload={"pr_number": 42, "unrelated_field": "ignored_in_dedup"},
            dedup_key="pr-42-commit-abc",
        )
        # Deduplication hash must be strictly deterministic across identical source/event_type/target/dedup_key
        self.assertEqual(env1.compute_dedup_hash(), env2.compute_dedup_hash())
        self.assertEqual(len(env1.compute_dedup_hash()), 64)

    def test_idempotency_filter_blocks_replay(self):
        filter_engine = IdempotencyFilter()
        env = EventEnvelope(
            source="cron",
            event_type="nightly_audit",
            target="repo:codex",
            payload={"job": "audit"},
            dedup_key="2026-11-05-midnight",
        )
        # First submission passes
        self.assertTrue(filter_engine.check_and_record(env))

        # Replayed submission must raise DuplicateEventIgnored
        with self.assertRaises(DuplicateEventIgnored):
            filter_engine.check_and_record(env)

    def test_envelope_validation_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            EventEnvelope(
                source="",  # Missing source
                event_type="test",
                target="repo:codex",
                payload={},
                dedup_key="k1",
            )

        with self.assertRaises(ValueError):
            EventEnvelope(
                source="test",
                event_type="",  # Missing event_type
                target="repo:codex",
                payload={},
                dedup_key="k1",
            )


if __name__ == "__main__":
    unittest.main()
