import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.journal import AppendOnlyJournal, JournalTamperError
from harness.types import JournalEvent


class TestAppendOnlyJournal(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_path = Path(self.temp_dir.name) / "test_journal.jsonl"
        self.journal = AppendOnlyJournal(self.journal_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_append_and_read_single_event(self):
        event = JournalEvent(
            event_type="PIPELINE_INIT",
            payload={"pipeline_id": "pipe_001", "ttl": 8},
            entity_ids=["pipe_001"],
        )
        persisted = self.journal.append(event)
        self.assertIsNotNone(persisted.checksum)
        self.assertIsNotNone(persisted.event_id)
        self.assertIsNotNone(persisted.timestamp)

        events = self.journal.read_all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "PIPELINE_INIT")
        self.assertEqual(events[0].payload["pipeline_id"], "pipe_001")
        self.assertEqual(events[0].checksum, persisted.checksum)

    def test_append_multiple_events_chronological(self):
        e1 = JournalEvent(event_type="STEP1_START", payload={"step": 1}, entity_ids=["pipe_001"])
        e2 = JournalEvent(event_type="STEP1_DONE", payload={"verdict": "SHIP"}, entity_ids=["pipe_001"])
        e3 = JournalEvent(event_type="STEP2_START", payload={"step": 2}, entity_ids=["pipe_001"])

        self.journal.append(e1)
        self.journal.append(e2)
        self.journal.append(e3)

        events = self.journal.read_all()
        self.assertEqual(len(events), 3)
        self.assertEqual([e.event_type for e in events], ["STEP1_START", "STEP1_DONE", "STEP2_START"])

    def test_integrity_verification_pass(self):
        self.journal.append(JournalEvent(event_type="STEP_A", payload={"data": 123}))
        self.journal.append(JournalEvent(event_type="STEP_B", payload={"data": 456}))
        self.assertTrue(self.journal.verify_integrity())

    def test_integrity_verification_fails_on_tamper(self):
        self.journal.append(JournalEvent(event_type="ORIGINAL", payload={"secure": True}))
        # Tamper with the raw file directly
        with open(self.journal_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tampered_record = json.loads(lines[0])
        tampered_record["payload"]["secure"] = False  # modify payload without updating checksum
        with open(self.journal_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(tampered_record) + "\n")

        with self.assertRaises(JournalTamperError):
            self.journal.read_all()

    def test_why_causal_trace(self):
        # pipe_001 events
        self.journal.append(JournalEvent(event_type="INIT", payload={"id": 1}, entity_ids=["pipe_001"]))
        # unrelated pipe_002 event
        self.journal.append(JournalEvent(event_type="UNRELATED", payload={"id": 2}, entity_ids=["pipe_002"]))
        # pipe_001 continued
        self.journal.append(JournalEvent(event_type="WITNESS_MINTED", payload={"witness_id": "wit_abc"}, entity_ids=["pipe_001", "wit_abc"]))

        trace_wit = self.journal.why("wit_abc")
        self.assertEqual(len(trace_wit), 1)
        self.assertEqual(trace_wit[0].event_type, "WITNESS_MINTED")

        trace_pipe = self.journal.why("pipe_001")
        self.assertEqual(len(trace_pipe), 2)
        self.assertEqual([e.event_type for e in trace_pipe], ["INIT", "WITNESS_MINTED"])

    def test_why_nonexistent_entity(self):
        self.journal.append(JournalEvent(event_type="INIT", payload={"id": 1}, entity_ids=["pipe_001"]))
        trace = self.journal.why("nonexistent_id")
        self.assertEqual(trace, [])


if __name__ == "__main__":
    unittest.main()
