import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for p in (SRC, TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import darwin_optimize_procedure as dop


SAMPLE_PROCEDURE_MD = """---
id: "procedure-20261102-test01"
type: "procedure"
title: "服务部署与端口冲突解决规程"
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
  - "troubleshooting"
content: |-
  本地服务部署与端口冲突解决规程：
  
  1. 启动服务：
  运行 python main.py 启动服务。如果遇到问题可以考虑重试。
  
  2. 端口冲突排查：
  建议使用 lsof -i:8080 查看占用进程，并视情况而定杀掉占用进程。
---

# 服务部署与端口冲突解决规程

该记忆的结构化内容保存在 front matter 的 content 字段中。
"""


class DarwinOptimizeProcedureTests(unittest.TestCase):
    def test_parse_procedure_markdown(self):
        parsed = dop.parse_procedure_markdown(SAMPLE_PROCEDURE_MD)
        self.assertEqual(parsed["id"], "procedure-20261102-test01")
        self.assertEqual(parsed["title"], "服务部署与端口冲突解决规程")
        self.assertEqual(parsed["workspace"], "personal")
        self.assertIn("python main.py", parsed["content"])

    def test_diagnose_procedure_identifies_gaps(self):
        parsed = dop.parse_procedure_markdown(SAMPLE_PROCEDURE_MD)
        diag = dop.diagnose_procedure(parsed["content"])
        self.assertGreater(len(diag["soft_terms"]), 0)  # "可以考虑", "建议", "视情况而定"
        self.assertTrue(diag["missing_failure_branches"])  # lacks explicit "if X fails -> fallback to Y"
        self.assertTrue(diag["missing_blacklist"])  # lacks explicit blacklist/anti-patterns

    def test_generate_test_prompts(self):
        parsed = dop.parse_procedure_markdown(SAMPLE_PROCEDURE_MD)
        prompts = dop.generate_test_prompts(parsed["title"], parsed["content"])
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0]["scenario"], "happy_path")
        self.assertEqual(prompts[1]["scenario"], "edge_case_failure")

    def test_pairwise_evaluation_prefers_structured_version(self):
        parsed = dop.parse_procedure_markdown(SAMPLE_PROCEDURE_MD)
        diag = dop.diagnose_procedure(parsed["content"])
        optimized = dop.generate_optimized_procedure(parsed, diag)
        prompts = dop.generate_test_prompts(parsed["title"], parsed["content"])

        eval_res = dop.evaluate_procedure_pairwise(parsed["content"], optimized, prompts)
        self.assertEqual(eval_res["winner"], "mutated")
        self.assertGreater(eval_res["mutated_score"], eval_res["baseline_score"])
        self.assertTrue(eval_res["ratchet_retained"])

    def test_end_to_end_darwin_optimize_creates_candidate(self):
        with tempfile.TemporaryDirectory() as temp_root, tempfile.TemporaryDirectory() as temp_state:
            root = Path(temp_root)
            state = Path(temp_state)
            
            # Setup minimal LAOS memory structure
            proc_dir = root / "memory" / "procedures"
            proc_dir.mkdir(parents=True)
            proc_file = proc_dir / "procedure-20261102-test01-service-deploy.md"
            proc_file.write_text(SAMPLE_PROCEDURE_MD, encoding="utf-8")

            # Initialize memory store
            from memory import init_store
            init_store(str(root))

            result = dop.darwin_optimize(proc_file, root=root, state_dir=state, dry_run=False)
            self.assertEqual(result["status"], "candidate_created")
            self.assertIn("candidate_id", result)
            self.assertTrue((root / result["candidate_path"]).is_file())

    def test_end_to_end_darwin_optimize_dry_run(self):
        with tempfile.TemporaryDirectory() as temp_root, tempfile.TemporaryDirectory() as temp_state:
            root = Path(temp_root)
            state = Path(temp_state)
            
            proc_dir = root / "memory" / "procedures"
            proc_dir.mkdir(parents=True)
            proc_file = proc_dir / "procedure-20261102-test01-service-deploy.md"
            proc_file.write_text(SAMPLE_PROCEDURE_MD, encoding="utf-8")

            from memory import init_store
            init_store(str(root))

            result = dop.darwin_optimize(proc_file, root=root, state_dir=state, dry_run=True)
            self.assertEqual(result["status"], "dry_run_success")
            self.assertIsNone(result["candidate_id"])
            self.assertIsNone(result["candidate_path"])
            self.assertTrue(result["eval_summary"]["ratchet_retained"])

    def test_end_to_end_with_initialized_db(self):
        with tempfile.TemporaryDirectory() as temp_root, tempfile.TemporaryDirectory() as temp_state:
            root = Path(temp_root)
            state = Path(temp_state)
            
            proc_dir = root / "memory" / "procedures"
            proc_dir.mkdir(parents=True)
            proc_file = proc_dir / "procedure-20261102-test01-service-deploy.md"
            proc_file.write_text(SAMPLE_PROCEDURE_MD, encoding="utf-8")

            from memory import init_store, db_init
            import argparse
            init_store(str(root))
            db_init(argparse.Namespace(root=str(root), state_dir=str(state), dry_run=False))

            result = dop.darwin_optimize(proc_file, root=root, state_dir=state, dry_run=False)
            self.assertEqual(result["status"], "candidate_created")
            self.assertIn("candidate_id", result)
            self.assertTrue((root / result["candidate_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
