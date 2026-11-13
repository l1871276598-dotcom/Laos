import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .event_envelope import EventEnvelope


class UnmatchedRouteError(Exception):
    """Raised when an incoming event fails to match any defined routing rule."""
    pass


@dataclass
class RouteDecision:
    rule_id: str
    target_host: str
    agent_adapter: str
    procedure_id: str
    token_budget: int = 50000
    require_gate: bool = False


class RuleRouter:
    """Evaluates rules.json definitions to route events to appropriate hosts, adapters, and procedures."""

    def __init__(self, rules_source: Union[Dict[str, Any], List[Dict[str, Any]], str, Path]):
        if isinstance(rules_source, (str, Path)):
            path = Path(rules_source)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(str(rules_source))
        else:
            data = rules_source

        if isinstance(data, dict):
            self.rules = data.get("rules", [])
        elif isinstance(data, list):
            self.rules = data
        else:
            self.rules = []

    def match(self, envelope: EventEnvelope) -> RouteDecision:
        for rule in self.rules:
            match_criteria = rule.get("match", {})
            src_match = match_criteria.get("source")
            evt_match = match_criteria.get("event_type")

            if (src_match is None or src_match == envelope.source) and (
                evt_match is None or evt_match == envelope.event_type
            ):
                return RouteDecision(
                    rule_id=rule.get("rule_id", "unnamed_rule"),
                    target_host=rule.get("target_host", "local"),
                    agent_adapter=rule.get("agent_adapter", "default"),
                    procedure_id=rule.get("procedure_id", "default_procedure"),
                    token_budget=int(rule.get("token_budget", 50000)),
                    require_gate=bool(rule.get("require_gate", False)),
                )

        raise UnmatchedRouteError(
            f"No matching rule found for event source='{envelope.source}', event_type='{envelope.event_type}'."
        )
