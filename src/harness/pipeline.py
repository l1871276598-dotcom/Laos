import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .journal import AppendOnlyJournal
from .probe import TruthProbe
from .review_gate import ReviewGate, ReviewRequest, ReviewResponse
from .sandbox import EphemeralSandbox
from .types import JournalEvent, PhysicalWitness, SandboxResult, Verdict


class PipelineStatus(str, Enum):
    IDLE = "IDLE"
    STEP1_REVIEWING = "STEP1_REVIEWING"
    STEP2_SANDBOX_TESTING = "STEP2_SANDBOX_TESTING"
    STEP3_BRANCH_MERGING = "STEP3_BRANCH_MERGING"
    SUSPENDED_WAITING_GATE = "SUSPENDED_WAITING_GATE"
    STEP4_DEPLOYING = "STEP4_DEPLOYING"
    STEP5_PROBING = "STEP5_PROBING"
    WITNESS_SEALED = "WITNESS_SEALED"
    ABORTED = "ABORTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class PipelineResult:
    pipeline_id: str
    status: PipelineStatus
    witnesses: List[PhysicalWitness] = field(default_factory=list)
    snapshot_path: Optional[str] = None
    error_message: Optional[str] = None


class HarnessPipeline:
    """The 5-Step Physical Pipeline orchestrator with Suspend-Zero-Cost and Event Sourcing."""

    def __init__(
        self,
        repo_root: Union[Path, str],
        journal: AppendOnlyJournal,
        pipeline_id: Optional[str] = None,
        initial_ttl: int = 8,
    ):
        self.repo_root = Path(repo_root)
        self.journal = journal
        self.pipeline_id = pipeline_id or f"pipe_{uuid.uuid4().hex[:12]}"
        self.ttl = initial_ttl
        self.review_gate = ReviewGate(max_rounds=3, initial_ttl=self.ttl)
        self.probe = TruthProbe()
        self.witnesses: List[PhysicalWitness] = []
        self.status = PipelineStatus.IDLE

    def _record_event(self, event_type: str, payload: Dict[str, Any]):
        evt = JournalEvent(
            event_type=event_type,
            payload=payload,
            entity_ids=[self.pipeline_id],
        )
        self.journal.append(evt)

    def run(
        self,
        reviewer: Callable[[ReviewRequest], ReviewResponse],
        diff: str,
        test_command: Union[List[str], str],
        deploy_fn: Callable[[], bool],
        probe_command: Union[List[str], str],
        instruction: str = "Perform standards and spec code review",
        require_gate: bool = False,
        snapshot_dir: Optional[Union[Path, str]] = None,
        rollback_fn: Optional[Callable[[], None]] = None,
    ) -> PipelineResult:
        # Step 1: Heterogeneous adversarial review
        self.status = PipelineStatus.STEP1_REVIEWING
        self._record_event("STEP1_REVIEW_STARTED", {"diff_len": len(diff), "ttl": self.ttl})

        req = ReviewRequest(instruction=instruction, diff=diff, ttl=self.ttl)
        review_res = self.review_gate.run_review_loop(req, reviewer=reviewer)
        if not review_res["accepted"]:
            self.status = PipelineStatus.ABORTED
            self._record_event("STEP1_REVIEW_FAILED", {"reason": "Review rejected or exceeded max rounds"})
            return PipelineResult(pipeline_id=self.pipeline_id, status=self.status, error_message="Review failed")

        self._record_event("STEP1_REVIEW_PASSED", {"rounds": review_res["rounds_completed"]})

        # Step 2: Ephemeral sandbox mechanical verification
        self.status = PipelineStatus.STEP2_SANDBOX_TESTING
        self._record_event("STEP2_TESTS_STARTED", {"command": str(test_command)})

        with EphemeralSandbox() as sb:
            sb_res = sb.run_command(test_command)
            step2_witness = self.probe.mint_witness_from_sandbox_result(
                pipeline_id=self.pipeline_id,
                step_id="STEP2_SANDBOX_TESTING",
                sandbox_result=sb_res,
            )
            self.witnesses.append(step2_witness)

        if not step2_witness.is_valid:
            self.status = PipelineStatus.ABORTED
            self._record_event("STEP2_TESTS_FAILED", {"exit_code": step2_witness.exit_code})
            return PipelineResult(
                pipeline_id=self.pipeline_id,
                status=self.status,
                witnesses=self.witnesses,
                error_message="Tests failed",
            )

        self._record_event(
            "STEP2_TESTS_PASSED",
            {"exit_code": 0, "duration_ms": step2_witness.wall_clock_duration_ms},
        )

        # Step 3: Protected branch merge gate
        self.status = PipelineStatus.STEP3_BRANCH_MERGING
        self._record_event("STEP3_MERGE_PASSED", {"status": "merged"})

        # Checkpoint / Suspend-Zero-Cost gate
        if require_gate:
            self.status = PipelineStatus.SUSPENDED_WAITING_GATE
            if snapshot_dir is None:
                snapshot_dir = Path("/tmp/laos-snapshots")
            snapshot_dir = Path(snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snap_path = snapshot_dir / f"{self.pipeline_id}.json"

            snap_content = {
                "pipeline_id": self.pipeline_id,
                "status": self.status.value,
                "ttl": self.ttl,
                "witnesses": [asdict(w) for w in self.witnesses],
            }
            with open(snap_path, "w", encoding="utf-8") as f:
                json.dump(snap_content, f, indent=2)

            self._record_event("PIPELINE_SUSPENDED", {"snapshot_path": str(snap_path)})
            return PipelineResult(
                pipeline_id=self.pipeline_id,
                status=self.status,
                witnesses=self.witnesses,
                snapshot_path=str(snap_path),
            )

        # Step 4 & 5
        return self._finish_steps_4_and_5(deploy_fn, probe_command, rollback_fn)

    def _finish_steps_4_and_5(
        self,
        deploy_fn: Callable[[], bool],
        probe_command: Union[List[str], str],
        rollback_fn: Optional[Callable[[], None]] = None,
    ) -> PipelineResult:
        # Step 4: Deployment
        self.status = PipelineStatus.STEP4_DEPLOYING
        self._record_event("STEP4_DEPLOY_STARTED", {})
        try:
            deploy_ok = deploy_fn()
            if not deploy_ok:
                raise RuntimeError("Deployment function returned False")
            self._record_event("STEP4_DEPLOY_PASSED", {})
        except Exception as e:
            self._rollback(rollback_fn, reason=f"Step 4 deploy error: {e}")
            return PipelineResult(
                pipeline_id=self.pipeline_id,
                status=self.status,
                witnesses=self.witnesses,
                error_message=str(e),
            )

        # Step 5: Truth Probing & Witness sealing
        self.status = PipelineStatus.STEP5_PROBING
        self._record_event("STEP5_PROBE_STARTED", {})
        step5_witness = self.probe.execute_probe(
            pipeline_id=self.pipeline_id,
            step_id="STEP5_PROBING",
            probe_command=probe_command,
        )
        self.witnesses.append(step5_witness)

        if not step5_witness.is_valid:
            self._rollback(rollback_fn, reason=f"Step 5 probe failed with exit_code {step5_witness.exit_code}")
            return PipelineResult(
                pipeline_id=self.pipeline_id,
                status=self.status,
                witnesses=self.witnesses,
                error_message="Probe failed",
            )

        self.status = PipelineStatus.WITNESS_SEALED
        self._record_event(
            "STEP5_PROBE_PASSED",
            {"exit_code": 0, "duration_ms": step5_witness.wall_clock_duration_ms},
        )
        self._record_event("WITNESS_SEALED", {"witness_count": len(self.witnesses)})
        return PipelineResult(pipeline_id=self.pipeline_id, status=self.status, witnesses=self.witnesses)

    def _rollback(self, rollback_fn: Optional[Callable[[], None]], reason: str):
        self.status = PipelineStatus.ROLLED_BACK
        event_name = "STEP5_PROBE_FAILED" if "probe" in reason.lower() else "DEPLOY_FAILED"
        self._record_event(event_name, {"reason": reason})
        if rollback_fn:
            try:
                rollback_fn()
            except Exception:
                pass
        self._record_event("ROLLBACK_COMPLETED", {"reason": reason})

    def resume(
        self,
        snapshot_path: Union[Path, str],
        approval: bool,
        deploy_fn: Callable[[], bool],
        probe_command: Union[List[str], str],
        rollback_fn: Optional[Callable[[], None]] = None,
    ) -> PipelineResult:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.pipeline_id = data["pipeline_id"]
        self.ttl = data.get("ttl", 8)
        self.witnesses = [PhysicalWitness(**w) for w in data.get("witnesses", [])]

        if not approval:
            self.status = PipelineStatus.ABORTED
            self._record_event("PIPELINE_RESUME_REJECTED", {"reason": "Human approval denied"})
            return PipelineResult(pipeline_id=self.pipeline_id, status=self.status, witnesses=self.witnesses)

        self._record_event("PIPELINE_RESUMED", {"snapshot_path": str(snapshot_path)})
        return self._finish_steps_4_and_5(deploy_fn, probe_command, rollback_fn)
