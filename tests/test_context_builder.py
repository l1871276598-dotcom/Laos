"""Tests for S5.6 Context Delivery with Adaptive Pattern Hints.

Contract: ADR-007 (LAOS vNext Context Delivery & Ephemeral Hints).
Verifies:
  - Canonical memory generation remains unmodified when pattern_graph is None.
  - Pattern hints are injected under a clear non-authority section when pattern_graph is provided.
  - Strict budget enforcement (used == len(text) <= limit).
  - INV-LEARN-01 non-authority boundary (canonical sources are not contaminated).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.context.builder import ContextBuilder
from src.learning_loop.pattern_engine import Pattern, PatternGraph


class FakeMemoryStore:
    def __init__(self, entries):
        self.entries = entries

    def active_relevant(self, query, workspace, project=None):
        return [
            e for e in self.entries
            if e.get("workspace") == workspace and (project is None or e.get("project") == project)
        ]


class ContextBuilderAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeMemoryStore([
            {
                "id": "mem_01",
                "workspace": "work",
                "title": "Database Connection Pool",
                "content": "Use connection pool with max 10 connections for SQLite",
                "tags": ["db", "sqlite"],
            }
        ])

        self.graph = PatternGraph()
        self.graph.add_pattern(Pattern(
            pattern_id="pat_tdd",
            name="London School TDD",
            description="Prefer test-first red-green-refactor with mocks for collaborator boundaries",
            tags=("tdd", "testing"),
            confidence=0.85,
            is_locked=True,
        ))
        self.graph.add_pattern(Pattern(
            pattern_id="pat_log",
            name="Pino Logging",
            description="Use pino structured logging",
            tags=("logging",),
            confidence=0.6,
        ))

    def test_default_builder_has_empty_hints_and_identical_contract(self):
        builder = ContextBuilder(self.store)
        pack = builder.build("sqlite", limit=500, workspace="work")

        self.assertEqual(pack["limit"], 500)
        self.assertEqual(pack["used"], len(pack["text"]))
        self.assertIn("Database Connection Pool", pack["text"])
        self.assertNotIn("ephemeral_hints", pack)
        self.assertEqual(pack["sources"], ["mem_01"])

    def test_adaptive_builder_injects_hints_within_budget(self):
        builder = ContextBuilder(self.store, pattern_graph=self.graph)
        pack = builder.build("tdd testing sqlite", limit=600, workspace="work")

        self.assertEqual(pack["limit"], 600)
        self.assertEqual(pack["used"], len(pack["text"]))
        self.assertLessEqual(pack["used"], 600)

        # Canonical memory is present
        self.assertIn("Database Connection Pool", pack["text"])
        # Non-authority hint section is present
        self.assertIn("tactical hints (non-authority):", pack["text"])
        self.assertIn("London School TDD", pack["text"])

        # Structured ephemeral_hints field is populated
        self.assertTrue(len(pack["ephemeral_hints"]) > 0)
        self.assertEqual(pack["ephemeral_hints"][0]["pattern_id"], "pat_tdd")

        # Canonical sources remain clean (INV-LEARN-01)
        self.assertEqual(pack["sources"], ["mem_01"])

    def test_hints_respect_tight_limit_without_overflow(self):
        builder = ContextBuilder(self.store, pattern_graph=self.graph)
        # Tight limit: 160 characters (barely fits canonical memory)
        pack = builder.build("tdd testing sqlite", limit=160, workspace="work")

        self.assertLessEqual(pack["used"], 160)
        self.assertEqual(pack["used"], len(pack["text"]))


if __name__ == "__main__":
    unittest.main()
