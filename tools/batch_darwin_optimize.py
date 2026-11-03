#!/usr/bin/env python3
"""tools/batch_darwin_optimize.py — Batch Darwin Optimization across all 7 canonical active procedures."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from darwin_optimize_procedure import darwin_optimize

data_root = Path("/Users/user/Library/Mobile Documents/com~apple~CloudDocs/ResearchAgent")
proc_dir = data_root / "memory" / "procedures"

targets = [
    "procedure-20261022-systems-haier-four-systems-workflow.md",
    "procedure-20261102-2f5bc77e-macOS-网易UU远程更新卡在-96-诊断与解决规程.md",
    "procedure-20261102-35134587-闲鱼虚拟电商全自动联动发布规程-huashu-design-huashu-icon-set.md",
    "procedure-20261102-d812c444-闲鱼发布服务MTOP令牌过期自愈与数据库持久化规程.md",
    "procedure-20261102-laos-cli-mcp-operations-LAOS-CLI运维与MCP能力面安全规程.md",
    "procedure-20261102-laos-multi-model-review-LAOS多模型对抗审查与受控分工规程.md",
    "procedure-20261102-xianyu-compliance-and-fulfillment.md",
]

print(f"Starting batch Darwin optimization for all {len(targets)} procedures...\n")

results = []
for i, t in enumerate(targets, 1):
    fpath = proc_dir / t
    print(f"[{i}/{len(targets)}] Optimizing: {t} ...")
    res = darwin_optimize(
        procedure_path=fpath,
        root=data_root,
        master_perspectives=["carmack", "taleb", "sre", "hickey"],
    )
    status = res.get("status")
    cid = res.get("candidate_id")
    cpath = res.get("candidate_path")
    eval_res = res["eval_summary"]
    spec_verdict = eval_res["agent_1_spec_judge"]["verdict"]
    spec_score = eval_res["agent_1_spec_judge"]["score_mutated"]
    safety_verdict = eval_res["agent_2_safety_judge"]["verdict"]
    safety_score = eval_res["agent_2_safety_judge"]["score_mutated"]
    
    print(f"  -> Status: {status}")
    print(f"  -> Candidate ID: {cid}")
    print(f"  -> Candidate Path: {cpath}")
    print(f"  -> Agent 1 (Spec): {spec_verdict} (Score: {spec_score})")
    print(f"  -> Agent 2 (Safety): {safety_verdict} (Score: {safety_score})")
    
    if "master_perspectives" in eval_res:
        m_revs = eval_res["master_perspectives"]["reviews"]
        for k, v in m_revs.items():
            print(f"     • {v['name']}: {v['verdict']} (Score: {v['score_mutated']}, delta: {v['delta']:+d})")
    print("-" * 60)
    results.append(res)

print(f"\nBatch optimization complete! Processed {len(results)} procedures.")
