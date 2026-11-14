import argparse
import importlib
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from .authority import AuthorityError, AuthorityStore, DECISION_ACTIONS, ReviewerProfile


class RiskTier(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


def assess_risk(record: Dict[str, Any]) -> RiskTier:
    """Assess operational risk of a candidate memory record based on blast radius."""
    if not isinstance(record, dict):
        return RiskTier.HIGH

    # Elevated confidentiality or work-domain changes are strictly HIGH risk
    conf = record.get("confidentiality", "personal")
    ws = record.get("workspace", "personal")
    if conf in ("internal", "restricted") or ws != "personal":
        return RiskTier.HIGH

    # Procedure and policy rules alter system execution logic -> HIGH risk
    mem_type = record.get("type", "")
    if mem_type in ("procedure", "policy"):
        return RiskTier.HIGH

    # Dangerous command / shell execution patterns in content
    content = record.get("content", "")
    if isinstance(content, str):
        dangerous_patterns = [
            "rm -rf", "DROP TABLE", "DELETE FROM", "--force", "eval(", "exec(",
            "chmod 777", "curl ", "wget ", "> /dev/", "mkfs"
        ]
        if any(pat in content for pat in dangerous_patterns):
            return RiskTier.HIGH

    # Uncertain confidence
    if record.get("confidence") == "uncertain":
        return RiskTier.HIGH

    return RiskTier.LOW


REVIEW_ACTIONS = DECISION_ACTIONS
_REVIEW_AUTHORITY = object()


def _canonical_backend_and_authority():
    backend = importlib.import_module("memory_distill")
    gate = importlib.import_module("review.gate")
    return backend, gate._REVIEW_AUTHORITY


class ReviewGate:
    """Two-phase review gate.

    ``review`` publishes an immutable decision and never changes memory state.
    ``activate`` is the only public transition path and consumes only a
    decision id plus the expected active-set generation.
    """

    def __init__(
        self,
        root,
        state_dir=None,
        backend=None,
        authority_store=None,
        reviewer_profile=None,
    ):
        try:
            self.root = Path(root).expanduser()
        except TypeError as exc:
            raise ValueError("root must be a filesystem path") from exc
        self.state_dir = None if state_dir is None else Path(state_dir).expanduser()
        canonical_backend, authority = _canonical_backend_and_authority()
        if backend is None:
            backend = canonical_backend
        required = (
            "_accept_candidate_impl",
            "_candidate_record",
            "_conflict_candidate_impl",
            "_reject_candidate_impl",
        )
        if any(not callable(getattr(backend, name, None)) for name in required):
            raise ValueError("review backend is invalid")
        self.backend = backend
        self._authority = authority if backend is canonical_backend else _REVIEW_AUTHORITY
        if authority_store is None:
            authority_store = AuthorityStore(self.root, self.state_dir)
        if not isinstance(authority_store, AuthorityStore):
            raise ValueError("authority_store is invalid")
        self.authority_store = authority_store
        if reviewer_profile is None:
            try:
                from profiles.store import current_profile

                active_profile = current_profile()
            except (ImportError, ValueError):
                active_profile = None
            if active_profile is None:
                reviewer_profile = ReviewerProfile("personal", "personal")
            else:
                reviewer_profile = ReviewerProfile(
                    active_profile.get("workspace"),
                    active_profile.get("confidentiality"),
                )
        if not isinstance(reviewer_profile, ReviewerProfile):
            raise ValueError("reviewer_profile must be an immutable ReviewerProfile")
        self.reviewer_profile = reviewer_profile

    def review(self, action, candidate_id, reason=None, workspace=None):
        """Publish a decision bound to the current exact candidate snapshot."""
        preflight = getattr(self.backend, "_preflight_candidate_impl", None)

        if workspace is not None:
            if workspace not in {"personal", "work"}:
                raise AuthorityError("invalid_workspace", "reviewer workspace is invalid")
            if workspace != self.reviewer_profile.workspace:
                raise AuthorityError("candidate_not_found", "candidate not found")

        def validate(record, snapshot):
            if callable(preflight):
                preflight(self.root, record, action, self.state_dir)

        decision = self.authority_store.publish_decision(
            action,
            candidate_id,
            reason=reason,
            workspace=self.reviewer_profile.workspace,
            confidentiality=self.reviewer_profile.confidentiality,
            validator=validate,
        )
        snapshot = decision["candidate_snapshot"]
        return {
            "status": "decided",
            "decision_id": decision["decision_id"],
            "decision_sha256": decision["decision_sha256"],
            "candidate_id": snapshot["candidate_id"],
            "candidate_artifact_sha256": snapshot["artifact_sha256"],
            "action": decision["action"],
            "expected_active_generation": decision["expected_active_generation"],
        }

    def assess_candidate_risk(self, candidate_id: str) -> RiskTier:
        """Inspect and assess candidate risk tier."""
        record = self.backend._candidate_record(self.root, candidate_id)
        return assess_risk(record)

    def auto_review_low_risk(
        self,
        candidate_id: str,
        reason: str = "Fast-path auto-review for low-risk verified candidate",
    ) -> Dict[str, Any]:
        """Fast-path auto-approval exclusively for verified low-risk candidates."""
        tier = self.assess_candidate_risk(candidate_id)
        if tier == RiskTier.HIGH:
            raise AuthorityError(
                "high_risk_requires_human_approval",
                f"Candidate {candidate_id} is evaluated as HIGH risk and strictly requires human approval.",
            )
        return self.review("accept", candidate_id, reason=reason)

    def activate(self, decision_id, expected_active_generation):
        """Apply one immutable decision through the generation CAS boundary."""

        def apply(decision):
            candidate_id = decision["candidate_snapshot"]["candidate_id"]
            action = decision["action"]
            if action == "reject":
                return self.backend._reject_candidate_impl(
                    argparse.Namespace(
                        root=str(self.root),
                        state_dir=str(self.state_dir),
                        id=candidate_id,
                        reason=decision["reason"],
                    ),
                    authority=self._authority,
                )
            if action == "conflict":
                return self.backend._conflict_candidate_impl(
                    argparse.Namespace(
                        root=str(self.root),
                        state_dir=str(self.state_dir),
                        id=candidate_id,
                    ),
                    authority=self._authority,
                )
            return self.backend._accept_candidate_impl(
                argparse.Namespace(
                    root=str(self.root),
                    state_dir=str(self.state_dir),
                    id=candidate_id,
                ),
                authority=self._authority,
            )

        receipt, backend_result = self.authority_store.activate(
            decision_id,
            expected_active_generation,
            apply,
        )
        distillation_status = self.authority_store.check_distillation_due()
        return {
            "status": receipt["status"],
            "activation_id": receipt["activation_id"],
            "activation_sha256": receipt["activation_sha256"],
            "decision_id": receipt["decision_id"],
            "candidate_id": receipt["candidate_id"],
            "action": receipt["action"],
            "previous_generation": receipt["previous_generation"],
            "active_generation": receipt["active_generation"],
            "authorized_records": receipt["authorized_records"],
            "meta_distillation_due": distillation_status["due"],
            "backend_status": backend_result.get("status")
            if isinstance(backend_result, dict)
            else None,
        }
