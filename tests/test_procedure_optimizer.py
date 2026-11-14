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
    validate_mental_model_triple_check,
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

    def test_ground_truth_execution_judge_vetoes_broken_syntax(self):
        judge = DualAgentBlindJudge()
        prompts = generate_test_prompts("Test", "Some baseline content")
        broken_code_mutated = (
            "### 1. 适用场景\n适用生产部署。\n\n"
            "### 2. 标准操作执行步骤\n"
            "1. 执行脚本：\n"
            "```python\ndef broken(:\n    pass\n```\n\n"
            "### 3. 失败分支与故障恢复\n重试不超过2次。\n\n"
            "### 4. 禁止动作与红线黑名单\n严禁删除数据。\n\n"
            "### 5. 诚实边界与失效宣告\n单机内存低于1GB失效。\n"
        )
        result = judge.evaluate("Some baseline content", broken_code_mutated, prompts)
        self.assertIn("ground_truth_judge", result)
        self.assertEqual(result["ground_truth_judge"]["verdict"], "FAIL")
        self.assertEqual(result["ratchet_decision"], "REVERT")

    def test_ground_truth_execution_judge_passes_valid_code(self):
        judge = DualAgentBlindJudge()
        prompts = generate_test_prompts("Test", "Some baseline content")
        valid_code_mutated = (
            "### 1. 适用场景\n适用生产部署。\n\n"
            "### 2. 标准操作执行步骤\n"
            "1. 执行脚本：\n"
            "```python\ndef run_step():\n    return 0\n```\n\n"
            "### 3. 失败分支与故障恢复\n有限重试配额为1次，失败切换fallback。\n\n"
            "### 4. 禁止动作与红线黑名单\n严禁删除生产数据库。\n\n"
            "### 5. 诚实边界与失效宣告\n单机内存低于1GB时宣告失效并停机。\n"
        )
        result = judge.evaluate("Some baseline content", valid_code_mutated, prompts)
        self.assertIn("ground_truth_judge", result)
        self.assertEqual(result["ground_truth_judge"]["verdict"], "PASS")
        self.assertGreaterEqual(result["ground_truth_judge"]["score_mutated"], 70)

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

    def test_mental_model_triple_check_validates_and_rejects_platitudes(self):
        # 1. Rigorous mental model with cross-domain, generative, and exclusive properties
        rigorous_model = (
            "状态机幂等退避：当分布式服务遇到非致命通信超时，由于可能处于中间态，"
            "因此推导必须依赖业务唯一幂等键并在重试时引入指数退避加随机抖动（Jitter），"
            "严格禁止裸重试，单次故障调用重试上限固定为 2 次。"
        )
        res_pass = validate_mental_model_triple_check(
            "状态机幂等退避法则",
            rigorous_model,
            tags=["resilience", "database"],
            evidence=["file:memory/procedures/procedure-1.md", "file:memory/procedures/procedure-2.md"],
        )
        self.assertTrue(res_pass["passed"])
        self.assertTrue(res_pass["cross_domain"])
        self.assertTrue(res_pass["generative"])
        self.assertTrue(res_pass["exclusive"])
        self.assertGreaterEqual(res_pass["triple_check_score"], 80)

        # 2. Platitude / cliché: lacks deductive generative power and exclusivity
        platitude = "平时开发要保持代码整洁，注意系统安全，团队之间要多沟通多写测试。"
        res_fail = validate_mental_model_triple_check(
            "代码建议",
            platitude,
            tags=["general"],
            evidence=[],
        )
        self.assertFalse(res_fail["passed"])
        self.assertFalse(res_fail["exclusive"])
        self.assertLess(res_fail["triple_check_score"], 60)

    def test_diagnose_and_mutate_honest_boundaries(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        diag = diagnose_procedure(parsed["content"])
        self.assertTrue(diag["missing_honest_boundaries"])

        mutated = mutate_procedure(parsed, diag)
        self.assertIn("### 5. 诚实边界与失效宣告", mutated)
        self.assertIn("规模边界限制", mutated)

        diag_mut = diagnose_procedure(mutated)
        self.assertFalse(diag_mut["missing_honest_boundaries"])

    def test_master_perspectives_distillation_in_review(self):
        parsed = parse_procedure_markdown(SAMPLE_PROCEDURE)
        diag = diagnose_procedure(parsed["content"])
        mutated = mutate_procedure(parsed, diag)
        prompts = generate_test_prompts(parsed["title"], parsed["content"])

        judge = DualAgentBlindJudge()
        result = judge.evaluate(
            parsed["content"],
            mutated,
            prompts,
            master_perspectives=["carmack", "taleb"],
        )
        self.assertIn("master_perspectives", result)
        self.assertEqual(result["master_perspectives"]["applied"], ["carmack", "taleb"])
        self.assertIn("carmack", result["master_perspectives"]["reviews"])
        self.assertIn("taleb", result["master_perspectives"]["reviews"])
        self.assertTrue(result["ratchet_retained"])


if __name__ == "__main__":
    unittest.main()
