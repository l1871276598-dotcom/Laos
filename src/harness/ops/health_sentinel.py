# -*- coding: utf-8 -*-
"""Anti-Entropy Health Sentinel: autonomous background scavenger and deadlock reclaimer."""

import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from harness.dispatch_queue import DispatchQueue
from harness.lease import LeaseManager


@dataclass
class HealthIssue:
    issue_type: str
    resource_id: str
    details: str
    healed: bool = True


@dataclass
class HealthStatus:
    is_healthy: bool
    active_leases_count: int
    orphan_sandboxes_cleaned: int
    expired_leases_reclaimed: int
    dead_letters_handled: int
    issues: List[HealthIssue] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class SandboxManager:
    """Helper manager for sandbox base directory discovery and scoping."""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        self.base_dir = str(base_dir or tempfile.gettempdir())


class HealthSentinel:
    """Anti-Entropy Sentinel responsible for orphan resource reclamation and deadlock healing."""

    def __init__(
        self,
        sandbox_manager: Optional[Any] = None,
        lease_manager: Optional[LeaseManager] = None,
        dispatch_queue: Optional[DispatchQueue] = None,
        orphan_ttl_seconds: float = 3600.0,
    ):
        if sandbox_manager is not None:
            self.base_dir = getattr(sandbox_manager, "base_dir", str(sandbox_manager))
        else:
            self.base_dir = None
        self.lease_manager = lease_manager
        self.dispatch_queue = dispatch_queue
        self.orphan_ttl_seconds = orphan_ttl_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def scan_and_heal(self, max_event_retries: int = 5) -> HealthStatus:
        issues: List[HealthIssue] = []
        cleaned_sandboxes = 0
        reclaimed_leases = 0
        handled_dead_letters = 0

        # 1. Scavenge orphan sandbox environments
        if self.base_dir and os.path.exists(self.base_dir):
            now = time.time()
            try:
                for entry in os.listdir(self.base_dir):
                    entry_path = os.path.join(self.base_dir, entry)
                    if os.path.isdir(entry_path):
                        mtime = os.path.getmtime(entry_path)
                        if (now - mtime) >= self.orphan_ttl_seconds:
                            shutil.rmtree(entry_path, ignore_errors=True)
                            cleaned_sandboxes += 1
                            issues.append(
                                HealthIssue(
                                    issue_type="orphan_sandbox",
                                    resource_id=entry_path,
                                    details=f"Cleaned orphan sandbox modified {(now - mtime):.1f}s ago.",
                                    healed=True,
                                )
                            )
            except Exception as e:
                issues.append(
                    HealthIssue(
                        issue_type="orphan_sandbox_scan_error",
                        resource_id=self.base_dir,
                        details=str(e),
                        healed=False,
                    )
                )

        # 2. Reclaim expired leases to heal deadlocks
        active_leases_count = 0
        if self.lease_manager is not None:
            with self.lease_manager._lock:
                now_mono = time.monotonic()
                expired_targets = []
                for target, lease in self.lease_manager._leases.items():
                    if lease.is_expired(now_mono):
                        expired_targets.append(target)
                    else:
                        active_leases_count += 1

                for target in expired_targets:
                    del self.lease_manager._leases[target]
                    reclaimed_leases += 1
                    issues.append(
                        HealthIssue(
                            issue_type="stale_lease",
                            resource_id=target,
                            details="Reclaimed expired entity lock lease.",
                            healed=True,
                        )
                    )

        # 3. Clean stale / poisoned dead-letter events in dispatch queue
        if self.dispatch_queue is not None:
            with self.dispatch_queue._cond:
                surviving_events = []
                for event in self.dispatch_queue._queue:
                    if getattr(event, "retry_count", 0) >= max_event_retries:
                        handled_dead_letters += 1
                        issues.append(
                            HealthIssue(
                                issue_type="dead_letter_event",
                                resource_id=event.event_id,
                                details=f"Removed dead-letter event exceeding retry limit ({event.retry_count}).",
                                healed=True,
                            )
                        )
                    else:
                        surviving_events.append(event)
                self.dispatch_queue._queue = surviving_events

        is_healthy = all(issue.healed for issue in issues)
        return HealthStatus(
            is_healthy=is_healthy,
            active_leases_count=active_leases_count,
            orphan_sandboxes_cleaned=cleaned_sandboxes,
            expired_leases_reclaimed=reclaimed_leases,
            dead_letters_handled=handled_dead_letters,
            issues=issues,
        )

    def start_background_loop(self, interval_seconds: float = 60.0) -> None:
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.scan_and_heal()
                except Exception:
                    pass
                time.sleep(interval_seconds)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_background_loop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
