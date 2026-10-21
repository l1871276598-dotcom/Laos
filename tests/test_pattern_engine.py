"""Tests for S5.5 PatternEngine — Deterministic Pure Node for Heuristic Self-Learning.

Contract: ADR-007 (LAOS vNext Heuristic Pattern Engine & Adaptive Learning Loop).
Pure computation. Standard library only. Zero I/O, zero LLM.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.learning_loop.pattern_engine import (
    Pattern,
    PatternGraph,
    calculate_pagerank,
    apply_outcome,
    apply_time_decay,
    get_top_hints,
    serialize_graph,
    deserialize_graph,
)


class TestPatternEngine(unittest.TestCase):
    def setUp(self):
        self.graph = PatternGraph()
        self.p1 = Pattern(
            pattern_id="pat_tdd",
            name="London School TDD",
            description="Prefer test-first red-green-refactor with mocks for collaborator boundaries",
            tags=("tdd", "testing", "mocking"),
            confidence=0.8,
            is_locked=True,  # EWC++ protected
            last_updated_epoch=1700000000,
        )
        self.p2 = Pattern(
            pattern_id="pat_pino",
            name="Structured Pino Logger",
            description="Use pino JSON logging instead of console.log",
            tags=("logging", "observability"),
            confidence=0.6,
            is_locked=False,
            last_updated_epoch=1700000000,
        )
        self.p3 = Pattern(
            pattern_id="pat_zod",
            name="Zod Schema Validation",
            description="Validate all external API responses using strict Zod schemas",
            tags=("validation", "schema", "api"),
            confidence=0.7,
            is_locked=False,
            last_updated_epoch=1700000000,
        )

    def test_add_and_retrieve_patterns(self):
        self.graph.add_pattern(self.p1)
        self.graph.add_pattern(self.p2)
        self.assertEqual(len(self.graph.patterns), 2)
        self.assertEqual(self.graph.get_pattern("pat_tdd").name, "London School TDD")

        # Duplicate ID should raise ValueError
        with self.assertRaises(ValueError):
            self.graph.add_pattern(self.p1)

    def test_pagerank_determinism_and_convergence(self):
        self.graph.add_pattern(self.p1)
        self.graph.add_pattern(self.p2)
        self.graph.add_pattern(self.p3)

        # Edges: p1 -> p2, p2 -> p3, p1 -> p3
        self.graph.add_edge("pat_tdd", "pat_pino", weight=1.0)
        self.graph.add_edge("pat_pino", "pat_zod", weight=1.0)
        self.graph.add_edge("pat_tdd", "pat_zod", weight=2.0)

        pr1 = calculate_pagerank(self.graph, damping=0.85, max_iter=100)
        pr2 = calculate_pagerank(self.graph, damping=0.85, max_iter=100)

        # Byte-identical determinism
        self.assertEqual(pr1, pr2)
        # Sum of ranks equals 1.0 (within tolerance)
        self.assertAlmostEqual(sum(pr1.values()), 1.0, places=5)
        # pat_zod has highest in-degree / weighted endorsements
        self.assertGreater(pr1["pat_zod"], pr1["pat_tdd"])

    def test_apply_outcome_pass_and_fail(self):
        self.graph.add_pattern(self.p2)  # initial confidence: 0.6
        epoch = 1700001000

        # PASS: +0.03
        updated = apply_outcome(self.graph, "pat_pino", outcome="PASS", now_epoch=epoch)
        self.assertAlmostEqual(updated.confidence, 0.63, places=4)
        self.assertEqual(updated.success_count, 1)
        self.assertEqual(updated.last_updated_epoch, epoch)

        # FAIL: -0.05
        updated2 = apply_outcome(self.graph, "pat_pino", outcome="FAIL", now_epoch=epoch + 100)
        self.assertAlmostEqual(updated2.confidence, 0.58, places=4)
        self.assertEqual(updated2.fail_count, 1)

    def test_time_decay_with_ewc_protection(self):
        self.graph.add_pattern(self.p1)  # is_locked = True
        self.graph.add_pattern(self.p2)  # is_locked = False, conf = 0.6

        # 10 days later = 86400 * 10 seconds
        future_epoch = 1700000000 + 86400 * 10
        apply_time_decay(self.graph, current_epoch=future_epoch, daily_decay_rate=0.005)

        # p1 is locked (EWC++ protected) -> confidence must not decay
        p1_now = self.graph.get_pattern("pat_tdd")
        self.assertEqual(p1_now.confidence, 0.8)

        # p2 is unlocked -> decays 10 * 0.005 = 0.05 -> 0.6 - 0.05 = 0.55
        p2_now = self.graph.get_pattern("pat_pino")
        self.assertAlmostEqual(p2_now.confidence, 0.55, places=4)

    def test_get_top_hints_relevance_and_ranking(self):
        self.graph.add_pattern(self.p1)
        self.graph.add_pattern(self.p2)
        self.graph.add_pattern(self.p3)
        self.graph.add_edge("pat_pino", "pat_zod", weight=2.0)

        # Query keywords: 'testing', 'mocking' -> p1 should rank highest
        hints = get_top_hints(self.graph, query_keywords=["testing", "unit"], top_k=2)
        self.assertTrue(len(hints) > 0)
        self.assertEqual(hints[0]["pattern_id"], "pat_tdd")
        self.assertIn("score", hints[0])

    def test_serialization_roundtrip(self):
        self.graph.add_pattern(self.p1)
        self.graph.add_pattern(self.p2)
        self.graph.add_edge("pat_tdd", "pat_pino", weight=1.5)

        serialized = serialize_graph(self.graph)
        deserialized = deserialize_graph(serialized)
        reserialized = serialize_graph(deserialized)

        self.assertEqual(
            json.dumps(serialized, sort_keys=True),
            json.dumps(reserialized, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
