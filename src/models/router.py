"""S5.7 Thompson Sampling Model Router & Token Telemetry Ledger.

Contract: ADR-007 (LAOS vNext Adaptive Model Router & Telemetry).
Pure algorithm + standard library.
Provides:
  - Multi-armed bandit (Thompson Sampling) for cost-adaptive model selection.
  - Prior learning Beta(alpha, beta) per intent.
  - Token telemetry and financial cost computation.
  - AdaptiveModelRouterBackend integrating with ModelBackend.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ModelBackend


# Reference pricing per 1,000,000 tokens (USD)
_PRICING_TABLE = {
    "local": {"prompt": 0.0, "completion": 0.0, "cache": 0.0},
    "haiku": {"prompt": 0.80, "completion": 4.00, "cache": 0.08},
    "sonnet": {"prompt": 3.00, "completion": 15.00, "cache": 0.30},
    "opus": {"prompt": 15.00, "completion": 75.00, "cache": 1.50},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00, "cache": 1.25},
    "default": {"prompt": 1.00, "completion": 3.00, "cache": 0.10},
}


def _resolve_pricing(model_name: str) -> Dict[str, float]:
    name = (model_name or "").lower().strip()
    if any(k in name for k in ("local", "ollama", "vllm", "fake")):
        return _PRICING_TABLE["local"]
    if "haiku" in name:
        return _PRICING_TABLE["haiku"]
    if "sonnet" in name:
        return _PRICING_TABLE["sonnet"]
    if "opus" in name:
        return _PRICING_TABLE["opus"]
    if "gpt-4" in name:
        return _PRICING_TABLE["gpt-4o"]
    return _PRICING_TABLE["default"]


def compute_estimated_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
) -> float:
    """Compute estimated USD cost based on token counts and model pricing."""
    rates = _resolve_pricing(model_name)
    cost = (
        (prompt_tokens * rates["prompt"])
        + (completion_tokens * rates["completion"])
        + (cache_read_tokens * rates["cache"])
    ) / 1_000_000.0
    return round(cost, 6)


class TokenLedger:
    """Audit-grade token telemetry ledger conforming to ADR-007 schema."""

    @staticmethod
    def create_entry(
        task_id: str,
        gate_phase: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        outcome: str = "PASS",
        evidence_digest: str = "",
        cost_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        cost = (
            cost_usd
            if cost_usd is not None
            else compute_estimated_cost(model, prompt_tokens, completion_tokens, cache_read_tokens)
        )
        return {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "task_id": str(task_id),
            "gate_phase": str(gate_phase),
            "model": str(model),
            "usage": {
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "cache_read_tokens": int(cache_read_tokens),
            },
            "cost_usd": cost,
            "evidence_digest": str(evidence_digest),
            "outcome": str(outcome).upper(),
        }

    @staticmethod
    def append_to_file(entry: Dict[str, Any], file_path: Path | str) -> None:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def summarize_file(file_path: Path | str) -> Dict[str, Any]:
        """Aggregate token ledger records into a financial summary dictionary."""
        path = Path(file_path)
        summary: Dict[str, Any] = {
            "total_records": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "models": {},
        }
        if not path.is_file():
            return summary
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    summary["total_records"] += 1
                    usage = record.get("usage", {})
                    pt = int(usage.get("prompt_tokens", 0))
                    ct = int(usage.get("completion_tokens", 0))
                    crt = int(usage.get("cache_read_tokens", 0))
                    cost = float(record.get("cost_usd", 0.0))
                    summary["total_prompt_tokens"] += pt
                    summary["total_completion_tokens"] += ct
                    summary["total_cache_read_tokens"] += crt
                    summary["total_cost_usd"] += cost

                    model = str(record.get("model", "unknown"))
                    if model not in summary["models"]:
                        summary["models"][model] = {
                            "calls": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "cost_usd": 0.0,
                        }
                    summary["models"][model]["calls"] += 1
                    summary["models"][model]["prompt_tokens"] += pt
                    summary["models"][model]["completion_tokens"] += ct
                    summary["models"][model]["cost_usd"] = round(
                        summary["models"][model]["cost_usd"] + cost, 6
                    )
            summary["total_cost_usd"] = round(summary["total_cost_usd"], 6)
        except Exception:
            pass
        return summary



class ThompsonSampler:
    """Bayesian Multi-Armed Bandit for cost-adjusted model routing (Beta priors)."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng if rng is not None else random.Random()
        self.tier_config: Dict[str, float] = {}  # tier_id -> cost_weight
        # priors[intent][tier_id] = {"alpha": float, "beta": float, "successes": int, "failures": int}
        self.priors: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def add_tier(
        self,
        tier: str,
        alpha: float = 1.0,
        beta: float = 1.0,
        cost_weight: float = 1.0,
    ) -> None:
        tier_clean = str(tier).strip()
        self.tier_config[tier_clean] = max(0.1, float(cost_weight))
        for intent in self.priors:
            if tier_clean not in self.priors[intent]:
                self.priors[intent][tier_clean] = {
                    "alpha": max(1.0, float(alpha)),
                    "beta": max(1.0, float(beta)),
                    "successes": 0,
                    "failures": 0,
                }

    def _ensure_intent(self, intent: str) -> None:
        if intent not in self.priors:
            self.priors[intent] = {}
            for tier, cost_w in self.tier_config.items():
                self.priors[intent][tier] = {
                    "alpha": 1.0,
                    "beta": 1.0,
                    "successes": 0,
                    "failures": 0,
                }

    def select_tier(
        self,
        intent: str = "general",
        candidate_tiers: Optional[List[str]] = None,
    ) -> str:
        """Sample theta ~ Beta(alpha, beta) and return tier with maximum utility (theta / cost_weight)."""
        intent_clean = str(intent).strip().lower() or "general"
        self._ensure_intent(intent_clean)

        available = candidate_tiers if candidate_tiers else list(self.tier_config.keys())
        if not available:
            raise ValueError("No model tiers registered in ThompsonSampler")

        best_tier = available[0]
        max_utility = -1.0

        for tier in sorted(available):
            if tier not in self.priors[intent_clean]:
                self.priors[intent_clean][tier] = {
                    "alpha": 1.0,
                    "beta": 1.0,
                    "successes": 0,
                    "failures": 0,
                }

            node = self.priors[intent_clean][tier]
            alpha = max(1.0, node["alpha"])
            beta = max(1.0, node["beta"])

            # Sample theta ~ Beta(alpha, beta)
            theta = self.rng.betavariate(alpha, beta)

            # Cost-adjusted utility: higher success rate per unit cost wins
            cost_w = self.tier_config.get(tier, 1.0)
            utility = theta / cost_w

            if utility > max_utility:
                max_utility = utility
                best_tier = tier

        return best_tier

    def record_outcome(
        self,
        intent: str,
        tier: str,
        success: bool,
        weight: float = 1.0,
    ) -> None:
        intent_clean = str(intent).strip().lower() or "general"
        self._ensure_intent(intent_clean)
        tier_clean = str(tier).strip()

        if tier_clean not in self.priors[intent_clean]:
            self.priors[intent_clean][tier_clean] = {
                "alpha": 1.0,
                "beta": 1.0,
                "successes": 0,
                "failures": 0,
            }

        node = self.priors[intent_clean][tier_clean]
        w = max(0.1, float(weight))
        if success:
            node["alpha"] += w
            node["successes"] += 1
        else:
            node["beta"] += w
            node["failures"] += 1

    def get_stats(self, intent: str = "general") -> Dict[str, Any]:
        intent_clean = str(intent).strip().lower() or "general"
        self._ensure_intent(intent_clean)
        stats = {}
        for tier, node in sorted(self.priors[intent_clean].items()):
            alpha = node["alpha"]
            beta = node["beta"]
            mean = alpha / (alpha + beta)
            stats[tier] = {
                "alpha": round(alpha, 3),
                "beta": round(beta, 3),
                "mean_success_rate": round(mean, 4),
                "success_count": node["successes"],
                "fail_count": node["failures"],
                "cost_weight": self.tier_config.get(tier, 1.0),
            }
        return stats


class AdaptiveModelRouterBackend(ModelBackend):
    """ModelBackend adapter that routes tasks dynamically using Thompson Sampling."""

    backend_id = "adaptive_router"

    def __init__(
        self,
        backends: Dict[str, ModelBackend],
        sampler: ThompsonSampler,
        ledger: Optional[TokenLedger] = None,
    ) -> None:
        if not backends or not isinstance(backends, dict):
            raise ValueError("backends must be a non-empty mapping of tier -> ModelBackend")
        self.backends = dict(backends)
        self.sampler = sampler
        self.ledger = ledger
        # Register capabilities from all underlying backends
        caps = set()
        for b in self.backends.values():
            caps.update(getattr(b, "capabilities", ()))
        self.capabilities = frozenset(caps)

    def complete(self, messages, tools=None, intent="general", **options):
        selected_tier = self.sampler.select_tier(intent, candidate_tiers=list(self.backends.keys()))
        backend = self.backends[selected_tier]

        response = backend.complete(messages, tools=tools, **options)

        # Log telemetry if usage is present
        if isinstance(response, dict):
            response["selected_tier"] = selected_tier
            usage = response.get("usage", {})
            if self.ledger and usage:
                task_id = options.get("task_id", "interactive")
                gate_phase = options.get("gate_phase", "EXECUTION")
                entry = self.ledger.create_entry(
                    task_id=task_id,
                    gate_phase=gate_phase,
                    model=getattr(backend, "model", selected_tier),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_tokens", 0),
                    outcome=options.get("outcome", "PASS"),
                )
                ledger_path = options.get("ledger_path")
                if ledger_path:
                    self.ledger.append_to_file(entry, ledger_path)

        return response

    def record_outcome(self, intent: str, tier: str, success: bool) -> None:
        self.sampler.record_outcome(intent, tier, success)
