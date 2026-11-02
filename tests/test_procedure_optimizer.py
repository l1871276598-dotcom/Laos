import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from procedures.optimizer import (
    DualAgentBlindJudge,
    ProcedureOptimizer,
    diagnose_procedure,
    generate_test_prompts,
    mutate_procedure,
    parse_procedure_markdown,
)
from memory import init_store

SAMPLE_PROCEDURE = """---
id: "procedure-20261102-test-deploy"
type: "procedure"
title: "服务部署与故障解决规程"
created: "2026-11-02"
updated: "2026-11-02"
status: "active"
scope: "global"
workspace: "personal"
confidentiality: "personal"
source: "user"
confidence: "confirmed"
tags:
  - "deployment"
content: |-
  服务部署与故障解决规程：
  
  1. 启动服务：
  运行 python main.py 启动服务。如果遇到问题可以考虑重试。
  
  2. 端口冲突排查：
  建议使用 lsof -i:8080 查看占用进程，并视情况而定杀掉占用进程。
---

# 服务部署与故障解决规程
"""


class MockModelBackend:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def review(self, messages):
        self.calls.append(messages)
        # Return structured JSON response for blind judge
        return json.dumps({
            "winner": "B",
            "score_a": 65,
            "score_b": 92,
            "critique": "Candidate B has zero soft terms and explicit failure recovery."
        })


class ProcedureOptimizerTests(unittest.TestCase):
    def test_parse_procedure_markdown(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        self.assertEqual(parsed["id"], "procedure-20261102-test-deploy")
        self.assertEqual(parsed["title"], "服务部署与故障解决规程")
        self.assertIn("python main.py", parsed["content"])

    def test_diagnose_procedure(self):
        diag = diagnose_procedure(SAMPLE_PROCEDURE)
        self.assertGreater(len(diag["soft_terms"]), 0)
        self.assertTrue(diag["missing_failure_branches"])
        self.assertTrue(diag["missing_blacklist"])
        self.assertIn("dim2_workflow", diag["scores"])

    def test_mutate_procedure_eliminates_soft_terms(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        diag = diagnose_procedure(parsed["content"])
        mutated = mutate_procedure(parsed, diag)

        self.assertNotIn("视情况而定", mutated)
        self.assertNotIn("可以考虑", mutated)
        self.assertIn("### 1. 适用场景与前置环境要求", mutated)
        self.assertIn("### 2. 标准操作执行步骤", mutated)
        self.assertIn("### 3. 失败分支与故障恢复", mutated)
        self.assertIn("### 4. 禁止动作与红线黑名单", mutated)

    def test_dual_agent_blind_judge_deterministic(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        diag = diagnose_procedure(parsed["content"])
        mutated = mutate_procedure(parsed, diag)
        prompts = generate_test_prompts(parsed["title"], parsed["content"])

        judge = DualAgentBlindJudge()
        result = judge.evaluate(parsed["content"], mutated, prompts)

        # Check Agent 1 (Spec & Actionability Judge)
        self.assertIn("agent_1_spec_judge", result)
        self.assertEqual(result["agent_1_spec_judge"]["verdict"], "PASS")
        self.assertGreater(result["agent_1_spec_judge"]["score_mutated"], result["agent_1_spec_judge"]["score_baseline"])

        # Check Agent 2 (Safety & Robustness Judge)
        self.assertIn("agent_2_safety_judge", result)
        self.assertEqual(result["agent_2_safety_judge"]["verdict"], "PASS")
        self.assertGreater(result["agent_2_safety_judge"]["score_mutated"], result["agent_2_safety_judge"]["score_baseline"])

        # Check Ratchet
        self.assertEqual(result["winner"], "mutated")
        self.assertTrue(result["ratchet_retained"])
        self.assertEqual(result["ratchet_decision"], "RETAIN")

    def test_dual_agent_blind_judge_with_llm_backend(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        diag = diagnose_procedure(parsed["content"])
        mutated = mutate_procedure(parsed, diag)
        prompts = generate_test_prompts(parsed["title"], parsed["content"])

        mock_backend = MockModelBackend()
        judge = DualAgentBlindJudge(model_backend=mock_backend)
        result = judge.evaluate(
            parsed["content"],
            mutated,
            prompts,
            evaluator_models=["gpt-4o", "claude-3-5-sonnet"]
        )

        self.assertTrue(result["ratchet_retained"])
        self.assertGreater(len(mock_backend.calls), 0)
        self.assertIn("llm_reviews", result)

    def test_ratchet_reverts_on_regression(self):
        # Mutated is worse (empty content)
        judge = DualAgentBlindJudge()
        prompts = generate_test_prompts("Test", "Some baseline content")
        result = judge.evaluate(
            "Some baseline content with good steps",
            "Bad mutated text",
            prompts,
        )
        self.assertFalse(result["ratchet_retained"])
        self.assertEqual(result["ratchet_decision"], "REVERT")

    def test_optimizer_end_to_end_candidate_creation(self):
        with tempfile.TemporaryDirectory() as temp_root, tempfile.TemporaryDirectory() as temp_state:
            root = Path(temp_root)
            state = Path(temp_state)
            init_store(str(root))

            proc_dir = root / "memory" / "procedures"
            proc_file = proc_dir / "procedure-20261102-test-deploy-service.md"
            proc_file.write_text(SAMPLE_PROCEDURE, encoding="utf-8")

            optimizer = ProcedureOptimizer(data_root=root, state_dir=state)
            res = optimizer.optimize("procedure-20261102-test-deploy", dry_run=False)

            self.assertEqual(res["status"], "candidate_created")
            self.assertEqual(res["procedure_id"], "procedure-20261102-test-deploy")
            self.assertTrue(res["eval_summary"]["ratchet_retained"])
            self.assertIsNotNone(res["candidate_id"])
            self.assertTrue((root / res["candidate_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
