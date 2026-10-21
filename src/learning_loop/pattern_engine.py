"""S5.5 PatternEngine — Deterministic Pure Node for Heuristic Self-Learning.

Pure function. No I/O, no LLM, no external network, no unseeded randomness.
Contract: ADR-007 (LAOS vNext Heuristic Pattern Engine & Adaptive Learning Loop).
Provides pattern extraction representation, PageRank authority ranking, EWC++
protection against time decay, and top-N hint filtering.
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, Tuple


class Pattern:
    """Immutable representation of an empirical learning pattern."""

    __slots__ = (
        "pattern_id",
        "name",
        "description",
        "tags",
        "confidence",
        "is_locked",
        "success_count",
        "fail_count",
        "last_updated_epoch",
    )

    def __init__(
        self,
        pattern_id: str,
        name: str,
        description: str,
        tags: Tuple[str, ...] | List[str] = (),
        confidence: float = 0.5,
        is_locked: bool = False,
        success_count: int = 0,
        fail_count: int = 0,
        last_updated_epoch: int = 0,
    ) -> None:
        self.pattern_id = str(pattern_id)
        self.name = str(name)
        self.description = str(description)
        self.tags = tuple(str(t) for t in tags)
        self.confidence = float(max(0.0, min(1.0, confidence)))
        self.is_locked = bool(is_locked)
        self.success_count = int(max(0, success_count))
        self.fail_count = int(max(0, fail_count))
        self.last_updated_epoch = int(last_updated_epoch)

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "confidence": round(self.confidence, 6),
            "is_locked": self.is_locked,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "last_updated_epoch": self.last_updated_epoch,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Pattern:
        return cls(
            pattern_id=data["pattern_id"],
            name=data["name"],
            description=data["description"],
            tags=data.get("tags", ()),
            confidence=data.get("confidence", 0.5),
            is_locked=data.get("is_locked", False),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            last_updated_epoch=data.get("last_updated_epoch", 0),
        )


class PatternGraph:
    """Deterministic in-memory directed graph of patterns and relational endorsements."""

    def __init__(self) -> None:
        self.patterns: Dict[str, Pattern] = {}
        # edges[u][v] = weight of edge from u to v
        self.edges: Dict[str, Dict[str, float]] = {}

    def add_pattern(self, pattern: Pattern) -> None:
        if pattern.pattern_id in self.patterns:
            raise ValueError(f"Pattern '{pattern.pattern_id}' already exists in graph")
        self.patterns[pattern.pattern_id] = pattern
        if pattern.pattern_id not in self.edges:
            self.edges[pattern.pattern_id] = {}

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        return self.patterns.get(pattern_id)

    def add_edge(self, from_id: str, to_id: str, weight: float = 1.0) -> None:
        if from_id not in self.patterns:
            raise ValueError(f"Source pattern '{from_id}' does not exist")
        if to_id not in self.patterns:
            raise ValueError(f"Target pattern '{to_id}' does not exist")
        if from_id not in self.edges:
            self.edges[from_id] = {}
        self.edges[from_id][to_id] = float(max(0.0, weight))


def calculate_pagerank(
    graph: PatternGraph,
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Dict[str, float]:
    """Compute PageRank scores deterministically using power iteration.

    Returns a dict mapping pattern_id -> normalized score (sum == 1.0).
    """
    nodes = sorted(graph.patterns.keys())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: 1.0}

    # Initial uniform distribution
    ranks = {u: 1.0 / n for u in nodes}

    # Precalculate outgoing weights
    out_weights: Dict[str, float] = {}
    for u in nodes:
        out_weights[u] = sum(graph.edges.get(u, {}).values())

    for _ in range(max_iter):
        new_ranks: Dict[str, float] = {u: 0.0 for u in nodes}
        dangling_sum = 0.0

        for u in nodes:
            out_w = out_weights[u]
            if out_w > 0:
                for v, w in sorted(graph.edges.get(u, {}).items()):
                    new_ranks[v] += damping * ranks[u] * (w / out_w)
            else:
                dangling_sum += ranks[u]

        # Distribute base random jump + dangling node mass uniformly
        base = (1.0 - damping) / n + (damping * dangling_sum) / n
        diff = 0.0
        for u in nodes:
            new_ranks[u] += base
            diff += abs(new_ranks[u] - ranks[u])

        ranks = new_ranks
        if diff < tol:
            break

    # Normalize to sum to exactly 1.0
    total = sum(ranks.values())
    if total > 0:
        ranks = {u: r / total for u, r in ranks.items()}

    return ranks


def apply_outcome(
    graph: PatternGraph,
    pattern_id: str,
    outcome: str,
    now_epoch: int,
    pass_boost: float = 0.03,
    fail_penalty: float = 0.05,
) -> Pattern:
    """Update a pattern's confidence and statistics based on execution outcome."""
    pattern = graph.get_pattern(pattern_id)
    if not pattern:
        raise ValueError(f"Pattern '{pattern_id}' not found")

    outcome_clean = str(outcome).upper().strip()
    if outcome_clean == "PASS":
        new_conf = min(1.0, pattern.confidence + pass_boost)
        new_pattern = Pattern(
            pattern_id=pattern.pattern_id,
            name=pattern.name,
            description=pattern.description,
            tags=pattern.tags,
            confidence=new_conf,
            is_locked=pattern.is_locked,
            success_count=pattern.success_count + 1,
            fail_count=pattern.fail_count,
            last_updated_epoch=now_epoch,
        )
    elif outcome_clean == "FAIL":
        new_conf = max(0.0, pattern.confidence - fail_penalty)
        new_pattern = Pattern(
            pattern_id=pattern.pattern_id,
            name=pattern.name,
            description=pattern.description,
            tags=pattern.tags,
            confidence=new_conf,
            is_locked=pattern.is_locked,
            success_count=pattern.success_count,
            fail_count=pattern.fail_count + 1,
            last_updated_epoch=now_epoch,
        )
    else:
        raise ValueError(f"Invalid outcome: {outcome}. Expected 'PASS' or 'FAIL'")

    graph.patterns[pattern_id] = new_pattern
    return new_pattern


def apply_time_decay(
    graph: PatternGraph,
    current_epoch: int,
    daily_decay_rate: float = 0.005,
) -> None:
    """Apply time-based confidence decay. Locked patterns (EWC++ protected) are exempt."""
    for pattern_id, pattern in list(graph.patterns.items()):
        if pattern.is_locked:
            continue
        elapsed_seconds = max(0, current_epoch - pattern.last_updated_epoch)
        days = elapsed_seconds / 86400.0
        if days > 0:
            decay_amount = days * daily_decay_rate
            new_conf = max(0.0, pattern.confidence - decay_amount)
            graph.patterns[pattern_id] = Pattern(
                pattern_id=pattern.pattern_id,
                name=pattern.name,
                description=pattern.description,
                tags=pattern.tags,
                confidence=new_conf,
                is_locked=pattern.is_locked,
                success_count=pattern.success_count,
                fail_count=pattern.fail_count,
                last_updated_epoch=current_epoch,
            )


def get_top_hints(
    graph: PatternGraph,
    query_keywords: Optional[List[str]] = None,
    top_k: int = 5,
    min_confidence: float = 0.5,
) -> List[dict]:
    """Retrieve top-K patterns ranked by PageRank, confidence, and keyword relevance."""
    pageranks = calculate_pagerank(graph)
    scored = []

    norm_keywords = [k.lower().strip() for k in (query_keywords or []) if k.strip()]

    for pid, p in sorted(graph.patterns.items()):
        if p.confidence < min_confidence:
            continue

        pr_score = pageranks.get(pid, 0.0)

        # Keyword match ratio
        if norm_keywords:
            text = (p.name + " " + p.description + " " + " ".join(p.tags)).lower()
            matches = sum(1 for kw in norm_keywords if kw in text)
            kw_score = matches / len(norm_keywords)
        else:
            kw_score = 1.0

        # Weighted combination: 40% confidence, 35% PageRank, 25% keyword match
        combined_score = (0.40 * p.confidence) + (0.35 * pr_score) + (0.25 * kw_score)
        scored.append((combined_score, p))

    scored.sort(key=lambda item: item[0], reverse=True)

    hints = []
    for score, p in scored[:top_k]:
        hints.append({
            "pattern_id": p.pattern_id,
            "name": p.name,
            "description": p.description,
            "confidence": round(p.confidence, 4),
            "score": round(score, 4),
            "is_locked": p.is_locked,
        })
    return hints


def serialize_graph(graph: PatternGraph) -> dict:
    """Serialize the pattern graph to a canonical dictionary structure."""
    return {
        "version": 1,
        "patterns": {pid: p.to_dict() for pid, p in sorted(graph.patterns.items())},
        "edges": {
            u: {v: round(w, 6) for v, w in sorted(targets.items())}
            for u, targets in sorted(graph.edges.items())
        },
    }


def deserialize_graph(data: dict) -> PatternGraph:
    """Reconstruct a PatternGraph from a serialized dictionary."""
    graph = PatternGraph()
    for pid, pdata in data.get("patterns", {}).items():
        graph.add_pattern(Pattern.from_dict(pdata))
    for u, targets in data.get("edges", {}).items():
        for v, w in targets.items():
            graph.add_edge(u, v, weight=float(w))
    return graph
