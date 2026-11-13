import json
import os
from pathlib import Path
from typing import List, Union

from .types import JournalEvent


class JournalTamperError(Exception):
    """Raised when an event's checksum fails integrity verification."""
    pass


class AppendOnlyJournal:
    """An append-only, crash-consistent event journal inspired by the Khazix pattern."""

    def __init__(self, path: Union[Path, str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: JournalEvent) -> JournalEvent:
        if not event.checksum:
            event.checksum = event.compute_checksum()

        record = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "entity_ids": list(event.entity_ids),
            "payload": event.payload,
            "checksum": event.checksum,
        }
        line = json.dumps(record, sort_keys=True) + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return event

    def read_all(self) -> List[JournalEvent]:
        if not self.path.exists():
            return []
        events: List[JournalEvent] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                data = json.loads(clean_line)
                event = JournalEvent(
                    event_id=data["event_id"],
                    event_type=data["event_type"],
                    timestamp=data["timestamp"],
                    entity_ids=data.get("entity_ids", []),
                    payload=data.get("payload", {}),
                    checksum=data.get("checksum", ""),
                )
                expected_checksum = event.compute_checksum()
                if event.checksum != expected_checksum:
                    raise JournalTamperError(
                        f"Integrity check failed at line {line_no} for event {event.event_id}: "
                        f"recorded={event.checksum}, computed={expected_checksum}"
                    )
                events.append(event)
        return events

    def verify_integrity(self) -> bool:
        try:
            self.read_all()
            return True
        except JournalTamperError:
            return False

    def why(self, entity_id: str) -> List[JournalEvent]:
        events = self.read_all()
        return [e for e in events if entity_id in e.entity_ids]
