"""Tests for S5.7 Thompson Sampling Model Router & Token Ledger.

Contract: ADR-007 (LAOS vNext Adaptive Model Router & Telemetry).
Verifies:
  - Thompson sampling Beta(alpha, beta) multi-armed bandit behavior.
  - Convergence to cheaper models on high success, fallback to premium on failures.
  - Token telemetry and financial ledger calculation.
  - Integration with ModelBackend and ModelBackendRegistry.
"""

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.models.base import ModelBackend
from src.models.registry import ModelBackendRegistry
from src.models.router import (
    AdaptiveModelRouterBackend,
    ThompsonSampler,
    TokenLedger,
    compute_estimated_cost,
)


class DummyBackend(ModelBackend):
    def __init__(self, name, response_text):
        self.backend_id = name
        self.response_text = response_text
        self.calls = []

    def complete(self, messages, tools=None, **options):
        self.calls.append({"messages": messages, "options": options})
        return {
            "content": self.response_text,
            "tool_calls": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }


class ThompsonSamplerTests(unittest.TestCase):
    def test_sampler_determinism_with_seed(self):
        rng1 = random.Random(42)
        sampler1 = ThompsonSampler(rng=rng1)
        sampler1.add_tier("cheap", alpha=2.0, beta=1.0, cost_weight=1.0)
        sampler1.add_tier("expensive", alpha=5.0, beta=1.0, cost_weight=4.0)

        rng2 = random.Random(42)
        sampler2 = ThompsonSampler(rng=rng2)
        sampler2.add_tier("cheap", alpha=2.0, beta=1.0, cost_weight=1.0)
        sampler2.add_tier("expensive", alpha=5.0, beta=1.0, cost_weight=4.0)

        choices1 = [sampler1.select_tier("ast_task") for _ in range(10)]
        choices2 = [sampler2.select_tier("ast_task") for _ in range(10)]

        self.assertEqual(choices1, choices2)

    def test_sampler_shifts_preference_on_feedback(self):
        rng = random.Random(100)
        sampler = ThompsonSampler(rng=rng)
        sampler.add_tier("cheap", alpha=1.0, beta=1.0, cost_weight=1.0)
        sampler.add_tier("premium", alpha=1.0, beta=1.0, cost_weight=5.0)

        # Simulate cheap tier constantly succeeding on 'boilerplate'
        for _ in range(30):
            sampler.record_outcome("boilerplate", "cheap", success=True)

        stats = sampler.get_stats("boilerplate")
        self.assertGreater(stats["cheap"]["mean_success_rate"], 0.9)

        # Sampling boilerplate should overwhelmingly favor cheap
        selections = [sampler.select_tier("boilerplate") for _ in range(50)]
        self.assertGreater(selections.count("cheap"), 40)

        # Simulate cheap tier failing on 'complex_proof'
        for _ in range(20):
            sampler.record_outcome("complex_proof", "cheap", success=False)
            sampler.record_outcome("complex_proof", "premium", success=True)

        # Sampling complex_proof should now prefer premium despite higher cost
        selections_complex = [sampler.select_tier("complex_proof") for _ in range(50)]
        self.assertGreater(selections_complex.count("premium"), 30)


class TokenLedgerTests(unittest.TestCase):
    def test_cost_calculation(self):
        # Local model is free
        self.assertEqual(compute_estimated_cost("local-ollama", 1000, 500), 0.0)

        # Claude Haiku pricing ($0.80 / 1M input, $4.00 / 1M output)
        cost_haiku = compute_estimated_cost("claude-3-5-haiku", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_haiku, 4.80, places=2)

        # Cache reads are cheaper ($0.08 / 1M)
        cost_cached = compute_estimated_cost("claude-3-5-haiku", 1_000_000, 0, cache_read_tokens=1_000_000)
        self.assertAlmostEqual(cost_cached, 0.88, places=2)

    def test_record_formatting(self):
        ledger = TokenLedger()
        entry = ledger.create_entry(
            task_id="task_verify_01",
            gate_phase="G4_AST",
            model="claude-3-5-haiku",
            prompt_tokens=1000,
            completion_tokens=200,
            outcome="PASS",
            evidence_digest="sha256:abc12345",
        )
        self.assertEqual(entry["task_id"], "task_verify_01")
        self.assertEqual(entry["gate_phase"], "G4_AST")
        self.assertEqual(entry["outcome"], "PASS")
        self.assertGreater(entry["cost_usd"], 0.0)


class AdaptiveModelRouterBackendTests(unittest.TestCase):
    def test_router_delegates_and_tracks(self):
        backend_cheap = DummyBackend("cheap_backend", "cheap answer")
        backend_premium = DummyBackend("premium_backend", "premium answer")

        sampler = ThompsonSampler(rng=random.Random(1))
        sampler.add_tier("cheap", cost_weight=1.0)
        sampler.add_tier("premium", cost_weight=10.0)

        router = AdaptiveModelRouterBackend(
            backends={"cheap": backend_cheap, "premium": backend_premium},
            sampler=sampler,
        )

        res = router.complete([{"role": "user", "content": "hello"}], intent="formatting")
        self.assertIn("content", res)
        self.assertIn(res["content"], ["cheap answer", "premium answer"])
        self.assertIn("selected_tier", res)

        # Record outcome
        router.record_outcome("formatting", res["selected_tier"], success=True)
        stats = sampler.get_stats("formatting")
        self.assertGreater(stats[res["selected_tier"]]["success_count"], 0)


if __name__ == "__main__":
    unittest.main()
