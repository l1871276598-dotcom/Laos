# -*- coding: utf-8 -*-
"""Cross-Model Context Recovery & Bounded Prompt Projection Engine."""

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from harness.decision_ledger import DecisionLedger
from harness.journal import AppendOnlyJournal
from harness.types import JournalEvent, Verdict


class StepName(str, Enum):
    STEP1_REVIEW = "STEP1_REVIEW"
    STEP2_TRANSIENT_VERIFY = "STEP2_TRANSIENT_VERIFY"
    STEP3_BRANCH_MERGE = "STEP3_BRANCH_MERGE"
    STEP4_ISOLATED_DEPLOY = "STEP4_ISOLATED_DEPLOY"
    STEP5_GROUND_TRUTH_PROBE = "STEP5_GROUND_TRUTH_PROBE"


@dataclass
class JournalEntry:
    step: Any
    verdict: Any
    evidence_hash: str = ""
    why: str = ""


class PipelineJournal(AppendOnlyJournal):
    """Wrapper around AppendOnlyJournal supporting high-level step recording."""

    def record(self, entry: Union[JournalEntry, JournalEvent]) -> JournalEvent:
        if isinstance(entry, JournalEvent):
            return self.append(entry)

        step_str = entry.step.value if hasattr(entry.step, "value") else str(entry.step)
        verdict_str = entry.verdict.value if hasattr(entry.verdict, "value") else str(entry.verdict)
        event = JournalEvent(
            event_type="pipeline_step",
            entity_ids=[step_str],
            payload={
                "step": step_str,
                "verdict": verdict_str,
                "evidence_hash": getattr(entry, "evidence_hash", ""),
                "why": getattr(entry, "why", ""),
            },
        )
        return self.append(event)

    @property
    def entries(self) -> List[Any]:
        results = []
        for e in self.read_all():
            if e.event_type == "pipeline_step":
                payload = e.payload
                results.append(
                    JournalEntry(
                        step=payload.get("step", ""),
                        verdict=payload.get("verdict", ""),
                        evidence_hash=payload.get("evidence_hash", ""),
                        why=payload.get("why", ""),
                    )
                )
            else:
                results.append(e)
        return results


@dataclass
class RecoveryPacket:
    context_id: str
    task_name: str
    current_breakpoint: str
    source_anchor_commit: str
    active_worktree_clean: bool = True
    verified_evidence_hashes: List[Dict[str, Any]] = field(default_factory=list)
    completed_slices: List[str] = field(default_factory=list)
    single_next_command: str = ""
    unresolved_blockers: List[str] = field(default_factory=list)
    unauthorized_action_rate: float = 0.0
    citations: List[Dict[str, Any]] = field(default_factory=list)
    negative_directives: List[str] = field(default_factory=list)
    active_directives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryPacket":
        return cls(
            context_id=data.get("context_id", ""),
            task_name=data.get("task_name", ""),
            current_breakpoint=data.get("current_breakpoint", ""),
            source_anchor_commit=data.get("source_anchor_commit", ""),
            active_worktree_clean=bool(data.get("active_worktree_clean", True)),
            verified_evidence_hashes=list(data.get("verified_evidence_hashes", [])),
            completed_slices=list(data.get("completed_slices", [])),
            single_next_command=data.get("single_next_command", ""),
            unresolved_blockers=list(data.get("unresolved_blockers", [])),
            unauthorized_action_rate=float(data.get("unauthorized_action_rate", 0.0)),
            citations=list(data.get("citations", [])),
            negative_directives=list(data.get("negative_directives", [])),
            active_directives=list(data.get("active_directives", [])),
        )

    def to_yaml(self) -> str:
        """Serializes the packet into clean canonical YAML using standard library only."""
        lines = [
            f"context_id: {self.context_id}",
            f"task_name: '{self.task_name}'",
            f"current_breakpoint: {self.current_breakpoint}",
            f"source_anchor_commit: '{self.source_anchor_commit}'",
            f"active_worktree_clean: {'true' if self.active_worktree_clean else 'false'}",
            f"unauthorized_action_rate: {self.unauthorized_action_rate}",
            f"single_next_command: '{self.single_next_command}'",
        ]

        def _append_list(name: str, items: List[Any]):
            lines.append(f"{name}:")
            if not items:
                lines.append("  []")
                return
            for it in items:
                if isinstance(it, dict):
                    d_str = json.dumps(it, ensure_ascii=False)
                    lines.append(f"  - {d_str}")
                else:
                    escaped = str(it).replace("'", "''")
                    lines.append(f"  - '{escaped}'")

        _append_list("completed_slices", self.completed_slices)
        _append_list("unresolved_blockers", self.unresolved_blockers)
        _append_list("negative_directives", self.negative_directives)
        _append_list("active_directives", self.active_directives)
        _append_list("verified_evidence_hashes", self.verified_evidence_hashes)
        _append_list("citations", self.citations)

        return "\n".join(lines) + "\n"

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "RecoveryPacket":
        """Parses standard YAML generated by to_yaml using standard library."""
        data: Dict[str, Any] = {
            "verified_evidence_hashes": [],
            "completed_slices": [],
            "unresolved_blockers": [],
            "citations": [],
            "negative_directives": [],
            "active_directives": [],
        }

        current_list_key: Optional[str] = None
        for line in yaml_str.splitlines():
            line_str = line.rstrip()
            if not line_str or line_str.startswith("#"):
                continue

            if line_str.startswith("  - "):
                val_str = line_str[4:].strip()
                if val_str.startswith("'") and val_str.endswith("'"):
                    val_str = val_str[1:-1].replace("''", "'")
                elif val_str.startswith("{") and val_str.endswith("}"):
                    try:
                        val_str = json.loads(val_str)
                    except Exception:
                        pass
                if current_list_key:
                    data[current_list_key].append(val_str)
                continue
            elif line_str.startswith("  []"):
                continue

            if ":" in line_str:
                k, v = line_str.split(":", 1)
                k = k.strip()
                v = v.strip()
                if v == "":
                    current_list_key = k
                else:
                    current_list_key = None
                    if v.startswith("'") and v.endswith("'"):
                        v = v[1:-1].replace("''", "'")
                    elif v == "true":
                        v = True
                    elif v == "false":
                        v = False
                    data[k] = v

        return cls.from_dict(data)


def build_recovery_packet(
    context_id: str,
    task_name: str,
    breakpoint: str,
    anchor_commit: str,
    ledger: Optional[DecisionLedger] = None,
    journal: Optional[Any] = None,
    worktree_clean: bool = True,
    completed_slices: Optional[List[str]] = None,
    single_next_command: str = "",
    unresolved_blockers: Optional[List[str]] = None,
) -> RecoveryPacket:
    neg_directives: List[str] = []
    act_directives: List[str] = []
    evidence_hashes: List[Dict[str, Any]] = []

    if ledger is not None:
        for neg in ledger.get_negative_directives():
            neg_directives.append(f"{neg.topic}: {neg.rationale}")
        for act in ledger.get_active_directives():
            act_directives.append(act.topic)

    if journal is not None:
        entries = getattr(journal, "entries", None)
        if entries is None and hasattr(journal, "read_all"):
            entries = journal.read_all()
        if entries:
            for entry in entries:
                ev_hash = getattr(entry, "evidence_hash", "") or (
                    entry.payload.get("evidence_hash", "") if hasattr(entry, "payload") else ""
                )
                if ev_hash:
                    step_val = getattr(entry, "step", "") or (
                        entry.payload.get("step", "") if hasattr(entry, "payload") else ""
                    )
                    evidence_hashes.append({
                        "step": str(step_val),
                        "sha256": ev_hash,
                    })

    return RecoveryPacket(
        context_id=context_id,
        task_name=task_name,
        current_breakpoint=breakpoint,
        source_anchor_commit=anchor_commit,
        active_worktree_clean=worktree_clean,
        verified_evidence_hashes=evidence_hashes,
        completed_slices=completed_slices or [],
        single_next_command=single_next_command,
        unresolved_blockers=unresolved_blockers or [],
        unauthorized_action_rate=0.0,
        negative_directives=neg_directives,
        active_directives=act_directives,
    )


def render_bounded_prompt_projection(packet: RecoveryPacket, target_model: str = "codex") -> str:
    """Renders an immutable, bounded, proof-carrying prompt projection header for cross-model handoff."""
    neg_section = "\n".join(f"- ⛔ {d}" for d in packet.negative_directives) if packet.negative_directives else "- (None)"
    act_section = "\n".join(f"- ⚡ {d}" for d in packet.active_directives) if packet.active_directives else "- (None)"
    slices_section = "\n".join(f"- [x] {s}" for s in packet.completed_slices) if packet.completed_slices else "- (None)"

    return (
        f"# =====================================================================\n"
        f"# [LAOS BOUNDED CONTEXT PROJECTION (HANDOFF PROTOCOL)]\n"
        f"# TARGET_MODEL: {target_model.upper()}\n"
        f"# CONTEXT_ID: {packet.context_id}\n"
        f"# ANCHOR_COMMIT: {packet.source_anchor_commit}\n"
        f"# BREAKPOINT: {packet.current_breakpoint}\n"
        f"# WORKTREE_CLEAN: {packet.active_worktree_clean}\n"
        f"# NEXT_COMMAND: {packet.single_next_command}\n"
        f"# =====================================================================\n\n"
        f"## 1. 任务背景与权威断点\n"
        f"- **任务名称**: {packet.task_name}\n"
        f"- **权威断点**: `{packet.current_breakpoint}`\n"
        f"- **唯一下一步指令**: `{packet.single_next_command}`\n\n"
        f"## 2. 不可违背代际《定了不做》（Negative Directives / Non-Goals）\n"
        f"{neg_section}\n\n"
        f"## 3. 已确立《定的事》（Active Directives）\n"
        f"{act_section}\n\n"
        f"## 4. 已完成交付切片 (Completed Slices)\n"
        f"{slices_section}\n\n"
        f"---\n"
        f"> **接收模型指令**：直接从断点 `{packet.current_breakpoint}` 继续执行，"
        f"严禁重新向人类确认《定了不做》清单中的任何事项，严禁破坏既有权威断点。\n"
    )


def validate_recovery_packet(packet: RecoveryPacket, current_commit: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Validates the recovery packet against system integrity constraints."""
    errors: List[str] = []

    if current_commit and current_commit != packet.source_anchor_commit:
        errors.append(
            f"Anchor commit mismatch: expected {packet.source_anchor_commit}, got {current_commit}. "
            f"Possible git split-brain or branch divergence."
        )

    if packet.unauthorized_action_rate > 0.0:
        errors.append(f"Unauthorized action rate {packet.unauthorized_action_rate} exceeds 0.0 tolerance.")

    if not packet.single_next_command.strip():
        errors.append("Single next command must be specified for deterministic handoff.")

    return len(errors) == 0, errors
