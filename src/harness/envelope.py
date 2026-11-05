import json
import re
from typing import Optional

from .types import TrailingEnvelope, Verdict


class EnvelopeMissingError(Exception):
    """Raised when a required control envelope is missing."""
    pass


class EnvelopeMalformedError(Exception):
    """Raised when a control envelope contains invalid JSON or schema."""
    pass


class CircuitBreakerTrippedError(Exception):
    """Raised when the hop-count fuse (TTL) reaches zero or below."""
    pass


ENVELOPE_PATTERN = re.compile(
    r"<!--\s*LAOS-CONTROL-ENVELOPE:\s*(.*?)\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def parse_envelope(text: str, require: bool = False) -> Optional[TrailingEnvelope]:
    """Extract and parse the trailing control envelope from agent text output."""
    matches = ENVELOPE_PATTERN.findall(text)
    if not matches:
        if require:
            raise EnvelopeMissingError("Missing required LAOS-CONTROL-ENVELOPE in output")
        return None

    # Pick the last occurrence if multiple are present
    raw_block = matches[-1].strip()
    try:
        data = json.loads(raw_block)
    except Exception as e:
        raise EnvelopeMalformedError(f"Failed to parse JSON in control envelope: {e}") from e

    if not isinstance(data, dict):
        raise EnvelopeMalformedError("Control envelope payload must be a JSON object")

    verdict_raw = data.get("verdict", "REJECT")
    verdict = Verdict.from_str(verdict_raw)
    ttl = int(data.get("ttl", 8))
    findings = data.get("findings", [])
    requires_action = bool(data.get("requires_action", False))
    suggested_actions = data.get("suggested_actions", [])

    return TrailingEnvelope(
        verdict=verdict,
        ttl=ttl,
        findings=findings,
        requires_action=requires_action,
        suggested_actions=suggested_actions,
    )


def serialize_envelope(envelope: TrailingEnvelope) -> str:
    """Format a TrailingEnvelope instance into a standardized Markdown comment block."""
    verdict_str = envelope.verdict.value if isinstance(envelope.verdict, Verdict) else str(envelope.verdict)
    payload = {
        "verdict": verdict_str,
        "ttl": envelope.ttl,
        "findings": envelope.findings,
        "requires_action": envelope.requires_action,
        "suggested_actions": envelope.suggested_actions,
    }
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"\n<!-- LAOS-CONTROL-ENVELOPE:\n{encoded}\n-->\n"


def strip_envelope(text: str) -> str:
    """Strip the trailing control envelope from the text, returning only the conversation body."""
    return ENVELOPE_PATTERN.sub("", text).strip()
