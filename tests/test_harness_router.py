import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.event_envelope import EventEnvelope
from harness.router import RouteDecision, RuleRouter, UnmatchedRouteError


class TestRuleRouter(unittest.TestCase):
    def setUp(self):
        self.rules_config = {
            "rules": [
                {
                  "rule_id": "github_pr_pipeline",
                  "match": {
                    "source": "github_webhook",
                    "event_type": "pull_request"
                  },
                  "target_host": "local-mac",
                  "agent_adapter": "codex_cli",
                  "procedure_id": "proc_code_review_v1",
                  "token_budget": 50000,
                  "require_gate": True
                },
                {
                  "rule_id": "nightly_security_cron",
                  "match": {
                    "source": "cron",
                    "event_type": "nightly_audit"
                  },
                  "target_host": "local-mac",
                  "agent_adapter": "deterministic_verifier",
                  "procedure_id": "proc_sandbox_audit",
                  "token_budget": 20000,
                  "require_gate": False
                }
            ]
        }
        self.router = RuleRouter(self.rules_config)

    def test_rule_matching_exact(self):
        env = EventEnvelope(
            source="github_webhook",
            event_type="pull_request",
            target="repo:codex",
            payload={"pr": 12},
            dedup_key="pr-12",
        )
        decision = self.router.match(env)
        self.assertIsInstance(decision, RouteDecision)
        self.assertEqual(decision.rule_id, "github_pr_pipeline")
        self.assertEqual(decision.target_host, "local-mac")
        self.assertEqual(decision.agent_adapter, "codex_cli")
        self.assertEqual(decision.token_budget, 50000)
        self.assertTrue(decision.require_gate)

    def test_rule_unmatched_raises_error(self):
        env = EventEnvelope(
            source="unknown_source",
            event_type="unknown_event",
            target="repo:codex",
            payload={},
            dedup_key="unk-1",
        )
        with self.assertRaises(UnmatchedRouteError):
            self.router.match(env)


if __name__ == "__main__":
    unittest.main()
