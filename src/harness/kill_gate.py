from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class KillCategory(str, Enum):
    DELETE_PRODUCTION_DATA = "DELETE_PRODUCTION_DATA"
    RESTART_CORE_SERVICE = "RESTART_CORE_SERVICE"
    IRREVERSIBLE_FINANCIAL_COST = "IRREVERSIBLE_FINANCIAL_COST"
    PUBLIC_COMMUNICATION = "PUBLIC_COMMUNICATION"
    CHANGE_CORE_DIRECTION = "CHANGE_CORE_DIRECTION"
    MUTATE_CREDENTIALS = "MUTATE_CREDENTIALS"
    ALTER_PERMISSIONS = "ALTER_PERMISSIONS"


class KillGateInterceptedError(Exception):
    """Raised when an action proposal is intercepted by the 7 Kill Gate security invariants."""
    pass


@dataclass
class ActionProposal:
    action_type: str
    description: str
    target: str
    payload: Dict[str, Any] = field(default_factory=dict)
    category: Optional[KillCategory] = None


@dataclass
class KillInterceptResult:
    is_intercepted: bool
    category: Optional[KillCategory] = None
    reason: str = ""


class KillGate:
    """Enforces fail-closed human gate interception on the 7 canonical high-risk action categories."""

    # Keywords associated with sensitive categories
    _CATEGORY_KEYWORDS = {
        KillCategory.DELETE_PRODUCTION_DATA: ["delete", "drop", "purge", "truncate", "rm -rf"],
        KillCategory.RESTART_CORE_SERVICE: ["restart", "reboot", "shutdown", "kill_service"],
        KillCategory.IRREVERSIBLE_FINANCIAL_COST: ["payment", "transfer", "bill", "spend", "purchase"],
        KillCategory.PUBLIC_COMMUNICATION: ["tweet", "post", "email_all", "publish_announcement"],
        KillCategory.CHANGE_CORE_DIRECTION: ["pivot", "deprecate_product", "change_business_model"],
        KillCategory.MUTATE_CREDENTIALS: ["secret", "password", "token", "rotate_key", "auth.json", "private_key"],
        KillCategory.ALTER_PERMISSIONS: ["chmod 777", "grant_admin", "sudoers", "disable_auth"],
    }

    def check(self, proposal: ActionProposal) -> KillInterceptResult:
        # 1. Direct explicit categorization
        if proposal.category is not None:
            return KillInterceptResult(
                is_intercepted=True,
                category=proposal.category,
                reason=f"Action explicitly classified as high-risk {proposal.category.value}.",
            )

        # 2. Heuristic inference across description, action_type, and target
        text_corpus = f"{proposal.action_type} {proposal.description} {proposal.target}".lower()
        for cat, keywords in self._CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in text_corpus:
                    return KillInterceptResult(
                        is_intercepted=True,
                        category=cat,
                        reason=f"Action matched high-risk keyword '{kw}' under category {cat.value}.",
                    )

        return KillInterceptResult(is_intercepted=False)

    def assert_safe_to_execute(self, proposal: ActionProposal) -> None:
        res = self.check(proposal)
        if res.is_intercepted:
            raise KillGateInterceptedError(
                f"Kill Gate Interception: [{res.category.value}] {res.reason} "
                f"Action '{proposal.action_type}' requires explicit human approval."
            )
