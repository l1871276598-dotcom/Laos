#!/usr/bin/env python3
"""tools/darwin_optimize_procedure.py — Darwin Autonomous Procedure Optimizer for LAOS.

Mounts Darwin Skill 2.0 (SkillLens 9-dim rubric + SkillOpt validation + pairwise ratchet)
onto LAOS Procedures.

Usage:
    python tools/darwin_optimize_procedure.py --procedure memory/procedures/procedure-xxx.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory import default_state_dir
from procedures.optimizer import (
    DualAgentBlindJudge,
    ProcedureOptimizer,
    diagnose_procedure,
    generate_test_prompts,
    mutate_procedure,
    parse_procedure_markdown,
)

# Backward-compatibility alias
generate_optimized_procedure = mutate_procedure


def evaluate_procedure_pairwise(
    baseline_text: str, mutated_text: str, test_prompts: List[Dict[str, str]]
) -> Dict[str, Any]:
    """Perform SkillLens paired evaluation on test prompts between baseline and mutated versions."""
    judge = DualAgentBlindJudge()
    res = judge.evaluate(baseline_text, mutated_text, test_prompts)
    return {
        "winner": res["winner"],
        "ratchet_retained": res["ratchet_retained"],
        "baseline_score": res["total_baseline_score"],
        "mutated_score": res["total_mutated_score"],
        "delta": res["combined_delta"],
        "details": res,
    }


def darwin_optimize(
    procedure_path: Path | str,
    root: Path | str | None = None,
    state_dir: Path | str | None = None,
    dry_run: bool = False,
    evaluator_models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute complete Darwin autonomous optimization cycle on a LAOS procedure."""
    proc_file = Path(procedure_path).expanduser().resolve(strict=True)

    if root is None:
        cur = proc_file.parent
        while cur != cur.parent:
            if (cur / "memory").is_dir():
                root = cur
                break
            cur = cur.parent
        if root is None:
            root = ROOT
    root = Path(root).expanduser().resolve(strict=True)

    if state_dir is None:
        state_dir = default_state_dir()
    state_dir = Path(state_dir).expanduser().resolve(strict=False)

    optimizer = ProcedureOptimizer(data_root=root, state_dir=state_dir)
    return optimizer.optimize(
        procedure_id_or_path=str(proc_file),
        dry_run=dry_run,
        evaluator_models=evaluator_models,
    )


def main():
    parser = argparse.ArgumentParser(description="Darwin Procedure Optimizer for LAOS")
    parser.add_argument("--procedure", required=True, help="Path or ID of procedure markdown file")
    parser.add_argument("--root", default=None, help="LAOS data root path")
    parser.add_argument("--state-dir", default=None, help="LAOS state directory")
    parser.add_argument("--dry-run", action="store_true", help="Run diagnosis and evaluation without creating candidate")
    parser.add_argument("--models", nargs="*", default=None, help="Optional model names for multi-model LLM judge")
    args = parser.parse_args()

    result = darwin_optimize(
        procedure_path=args.procedure,
        root=args.root,
        state_dir=args.state_dir,
        dry_run=args.dry_run,
        evaluator_models=args.models,
    )

    print("\n" + "=" * 60)
    print("  🧬 Darwin × LAOS Autonomous Procedure Optimization Report")
    print("=" * 60)
    print(f"Target Procedure : {result.get('title')} ({result.get('procedure_id')})")
    print(f"Source Digest    : {result.get('source_sha256')}")
    print(f"Status           : {result.get('status')}")
    print("\n[Diagnosis - SkillLens 9-Dim Rubric]")
    for k, v in result["diagnosis"]["scores"].items():
        print(f"  • {k:<20} : {v}/10")
    print(f"  • Soft Terms Found     : {result['diagnosis']['soft_terms']}")
    print(f"  • Missing Fallback     : {result['diagnosis']['missing_failure_branches']}")
    print(f"  • Missing Blacklist    : {result['diagnosis']['missing_blacklist']}")

    print("\n[Dual-Agent Blind Review - Baseline vs Mutated]")
    eval_res = result["eval_summary"]
    print(f"  • Winner               : {eval_res['winner'].upper()}")
    print(f"  • Ratchet Decision     : {eval_res['ratchet_decision']}")
    print(f"  • Agent 1 (Spec)       : {eval_res['agent_1_spec_judge']['verdict']} (Score: {eval_res['agent_1_spec_judge']['score_mutated']}/100, Δ: {eval_res['agent_1_spec_judge']['delta']:+d})")
    print(f"  • Agent 2 (Safety)     : {eval_res['agent_2_safety_judge']['verdict']} (Score: {eval_res['agent_2_safety_judge']['score_mutated']}/100, Δ: {eval_res['agent_2_safety_judge']['delta']:+d})")

    if eval_res.get("llm_reviews"):
        print("\n[Multi-Model LLM Reviews]")
        for rev in eval_res["llm_reviews"]:
            print(f"  • Model {rev['model']}: Winner={rev['winner']} (A={rev['score_a']}, B={rev['score_b']}) - {rev['critique']}")

    if result.get("candidate_id"):
        print("\n[LAOS Candidate Submission]")
        print(f"  • Candidate ID         : {result['candidate_id']}")
        print(f"  • Candidate Path       : {result['candidate_path']}")
        print("  • Awaiting Review      : Yes (Governed by Review Gate)")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
