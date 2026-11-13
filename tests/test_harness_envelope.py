import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from harness.envelope import (
    CircuitBreakerTrippedError,
    EnvelopeMalformedError,
    EnvelopeMissingError,
    parse_envelope,
    serialize_envelope,
    strip_envelope,
)
from harness.types import TrailingEnvelope, Verdict


class TestTrailingEnvelope(unittest.TestCase):
    def test_parse_valid_envelope(self):
        raw_output = """
I have thoroughly reviewed the diff. Everything looks robust and meets all standards.

<!-- LAOS-CONTROL-ENVELOPE:
{
  "verdict": "SHIP",
  "ttl": 7,
  "findings": [],
  "requires_action": false,
  "suggested_actions": ["merge"]
}
-->
"""
        env = parse_envelope(raw_output, require=True)
        self.assertIsNotNone(env)
        self.assertEqual(env.verdict, Verdict.SHIP)
        self.assertEqual(env.ttl, 7)
        self.assertEqual(env.findings, [])
        self.assertFalse(env.requires_action)
        self.assertEqual(env.suggested_actions, ["merge"])

    def test_parse_missing_envelope(self):
        raw_output = "Just some text without any control envelope."
        with self.assertRaises(EnvelopeMissingError):
            parse_envelope(raw_output, require=True)

        env = parse_envelope(raw_output, require=False)
        self.assertIsNone(env)

    def test_parse_malformed_envelope_raises(self):
        raw_output = """
Here is my review:
<!-- LAOS-CONTROL-ENVELOPE:
{ "verdict": "SHIP", "ttl": 7, invalid_json... }
-->
"""
        with self.assertRaises(EnvelopeMalformedError):
            parse_envelope(raw_output, require=True)

    def test_ttl_decrement_normal(self):
        env = TrailingEnvelope(
            verdict=Verdict.SHIP,
            ttl=5,
            findings=[],
        )
        decremented = env.decrement_ttl()
        self.assertEqual(decremented.ttl, 4)

    def test_ttl_fuse_circuit_breaker_tripped(self):
        env = TrailingEnvelope(
            verdict=Verdict.FIX_FIRST,
            ttl=1,
            findings=["Major bug"],
        )
        # ttl 1 decremented becomes 0, which should trip the fuse
        with self.assertRaises(CircuitBreakerTrippedError):
            env.decrement_ttl()

        # ttl 0 directly trips
        env_zero = TrailingEnvelope(verdict=Verdict.REJECT, ttl=0)
        with self.assertRaises(CircuitBreakerTrippedError):
            env_zero.decrement_ttl()

    def test_serialize_envelope(self):
        env = TrailingEnvelope(
            verdict=Verdict.SHIP,
            ttl=8,
            findings=[],
            requires_action=False,
            suggested_actions=["step2"],
        )
        serialized = serialize_envelope(env)
        self.assertIn("<!-- LAOS-CONTROL-ENVELOPE:", serialized)
        self.assertIn('"verdict": "SHIP"', serialized)
        self.assertIn('"ttl": 8', serialized)
        self.assertTrue(serialized.strip().endswith("-->"))

        # Roundtrip parse
        parsed = parse_envelope(serialized, require=True)
        self.assertEqual(parsed.verdict, env.verdict)
        self.assertEqual(parsed.ttl, env.ttl)

    def test_strip_envelope(self):
        raw_output = "Analysis text line 1\nAnalysis text line 2\n\n<!-- LAOS-CONTROL-ENVELOPE:\n{\"verdict\": \"SHIP\", \"ttl\": 8}\n-->\n"
        stripped = strip_envelope(raw_output)
        self.assertEqual(stripped, "Analysis text line 1\nAnalysis text line 2")


if __name__ == "__main__":
    unittest.main()
