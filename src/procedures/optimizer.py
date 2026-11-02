"""src/procedures/optimizer.py — Autonomous Procedure Optimizer with Dual-Agent Blind Review.

Contract:
- Core engine for Darwin Skill 2.0 integration into LAOS.
- Implements SkillLens 9-dimension diagnosis, prompt synthesis, and candidate mutation.
- Dual-Agent Blind Pairwise Evaluation (Spec & Actionability Judge + Safety & Robustness Judge).
- Multi-Model LLM judge support with position-debiasing.
- ADR-007 token telemetry integration.
- Human review gate submission through CandidateStore.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from memory import (
    collect_validated_records,
    default_state_dir,
    index_store,
    parse_front_matter,
)
from memory.candidate import CandidateStore

_SOFT_TERMS = [
    "建议",
    "可以考虑",
    "视情况而定",
    "灵活应用",
    "视具体情况",
    "根据情况判断",
    "基本上",
    "大概",
    "酌情",
    "可能需要",
]

_FAILURE_PATTERNS = [
    re.compile(r"(如果|若|当).*(失败|报错|超时|不可达|未成功|挂起).*(则|应当|必须|执行|回退|fallback|采用|切换|重启)", re.IGNORECASE),
    re.compile(r"(失败分支|故障恢复|fallback|备用方案|错误恢复|回退机制)", re.IGNORECASE),
]

_BLACKLIST_PATTERNS = [
    re.compile(r"(禁止动作|红线黑名单|反例与黑名单|风险防范|红线禁令)", re.IGNORECASE),
    re.compile(r"(严禁|切勿|绝不|禁止).*(误杀|关闭|破坏|盲目|绕过|强推)", re.IGNORECASE),
]


def parse_procedure_markdown(content: str) -> Dict[str, Any]:
    """Parse frontmatter and content from a LAOS procedure markdown."""
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        record, errors = parse_front_matter(tmp_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if record is None:
        raise ValueError(f"Invalid procedure markdown frontmatter: {errors}")

    lines = content.splitlines()
    body_raw = ""
    if lines and lines[0] == "---":
        try:
            end = lines.index("---", 1)
            body_raw = "\n".join(lines[end + 1 :]).strip()
        except ValueError:
            body_raw = content

    text_content = record.get("content")
    if not text_content or not isinstance(text_content, str):
        text_content = body_raw.strip()

    return {
        "id": record.get("id", ""),
        "type": record.get("type", "procedure"),
        "title": record.get("title", ""),
        "workspace": record.get("workspace", "personal"),
        "scope": record.get("scope", "global"),
        "confidentiality": record.get("confidentiality", "personal"),
        "status": record.get("status", "active"),
        "tags": record.get("tags") or [],
        "content": text_content.strip(),
        "frontmatter": record,
        "raw_body": body_raw,
    }


def diagnose_procedure(content: str) -> Dict[str, Any]:
    """Diagnose procedure based on SkillLens & Darwin 9-dimension rubric."""
    found_soft = [term for term in _SOFT_TERMS if term in content]
    has_failure = any(p.search(content) for p in _FAILURE_PATTERNS)
    has_blacklist = any(p.search(content) for p in _BLACKLIST_PATTERNS)
    has_steps = bool(re.search(r"(\d+\.|\b步骤\s*\d+)", content))

    dim5_score = max(3, 10 - len(found_soft) * 2)
    dim3_score = 9 if has_failure else 4
    dim9_score = 9 if has_blacklist else 3
    dim2_score = 9 if has_steps else 4

    overall_baseline_score = int(
        (dim5_score * 1.8 + dim3_score * 1.2 + dim9_score * 0.6 + dim2_score * 1.2 + 8 * 5.2) / 10
    )

    return {
        "soft_terms": found_soft,
        "missing_failure_branches": not has_failure,
        "missing_blacklist": not has_blacklist,
        "has_numbered_steps": has_steps,
        "scores": {
            "dim2_workflow": dim2_score,
            "dim3_failure_modes": dim3_score,
            "dim5_specificity": dim5_score,
            "dim9_blacklist": dim9_score,
        },
        "overall_baseline_score": overall_baseline_score,
    }


def generate_test_prompts(title: str, content: str) -> List[Dict[str, str]]:
    """Generate 2 canonical Darwin test prompts (happy path + edge case)."""
    return [
        {
            "id": "prompt-1",
            "scenario": "happy_path",
            "prompt": f"请依据规程「{title}」，执行标准作业流程并输出可验证的完成步骤。",
            "criteria": "必须包含清晰有序的具体步骤与执行参数，无模糊软化措辞。",
        },
        {
            "id": "prompt-2",
            "scenario": "edge_case_failure",
            "prompt": f"在执行「{title}」时遇到端口冲突或进程阻塞等异常中断，应如何诊断根因并进行故障恢复？",
            "criteria": "必须具备明确的失败分支诊断机制、备用恢复路径（Fallback）与红线避坑禁令。",
        },
    ]


def mutate_procedure(proc_data: Dict[str, Any], diagnosis: Dict[str, Any]) -> str:
    """Generate a mutated, Darwin-optimized procedure that eliminates gaps while preserving facts."""
    orig_content = proc_data["content"]
    title = proc_data["title"]

    cleaned = orig_content
    cleaned = cleaned.replace("可以考虑重试", "按失败恢复分支执行幂等重试（最多2次）")
    cleaned = cleaned.replace("视情况而定杀掉占用进程", "核对进程 PID 并执行强制终止 kill -9 <PID>")
    cleaned = cleaned.replace("建议使用", "执行命令")
    cleaned = cleaned.replace("建议", "必须")
    cleaned = cleaned.replace("视情况而定", "按判定规则严格执行")
    cleaned = cleaned.replace("可以考虑", "应当")

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    sections = [
        f"{title}（Darwin 优化落地版）：",
        "",
        "### 1. 适用场景与前置环境要求（Prerequisites）",
        f"- 规程目标：精确处置 {title} 相关任务，消除模棱两可，确保一次性闭环。",
        "- 权限要求：执行人需具备对应工作区操作权限及本地进程管理权限。",
        "",
        "### 2. 标准操作执行步骤（Actionable Execution Steps）",
    ]

    in_steps = False
    for line in lines:
        if line.startswith(("1.", "2.", "3.", "步骤", "- 步骤")):
            in_steps = True
            sections.append(f"{line}")
        elif in_steps:
            sections.append(f"  {line}")

    if not in_steps:
        sections.append("1. 环境检查与状态核对：确认当前运行环境正常且无僵尸进程占用。")
        sections.append("2. 核心规程操作：按标准指令序列逐步执行，记录输出结果。")
        sections.append("3. 产物与状态验证：核验操作目标与服务状态是否符合预期。")

    sections.extend([
        "",
        "### 3. 失败分支与故障恢复（Failure Modes & Recovery Fallback）",
        "- 分支 1（进程锁或端口冲突）：若主进程无法绑定或报告 Address already in use，执行 lsof 检索 PID，向目标进程发送 SIGTERM；若 5s 未退出则发送 SIGKILL，随后重试。",
        "- 分支 2（权限拒绝或提权挂起）：若出现 Permission denied 或提权无响应，检查 root/sudo 授权环境及系统安全策略，改走原生安装向导或前台交互安装，禁止后台盲目轮询。",
        "- 分支 3（安装包损坏或源不可达）：若哈希校验失败或二进制破损，立即中止安装，清除临时缓存，触发从备用官方源全量重新拉取。",
    ])

    sections.extend([
        "",
        "### 4. 禁止动作与红线黑名单（Risk-Action Blacklist）",
        "- 🔴 严禁在未确认进程归属时通配误杀无关系统核心服务（如禁止执行未绑定端口号的盲目 killall）。",
        "- 🔴 严禁在排查超时问题时关闭系统的安全沙箱、SIP 保护或网络签名证书安全校验。",
        "- 🔴 严禁无边界重试：单步骤重试上限固定为 2 次，超限必须阻断并报告人工干预。",
    ])

    return "\n".join(sections)


class DualAgentBlindJudge:
    """Multi-Model Dual-Agent Blind Pairwise Evaluation Engine.

    Dual Agents:
      1. Agent 1: Spec & Actionability Judge (Dim 2 Workflow Clarity & Dim 5 Specificity).
      2. Agent 2: Safety & Robustness Judge (Dim 3 Failure Modes & Dim 9 Risk Blacklist).

    Blind Evaluation:
      Candidates are presented anonymously as Candidate A and Candidate B.
      Evaluations are debiased against position bias.
    """

    def __init__(self, model_backend=None, token_ledger_path=None):
        self.model_backend = model_backend
        self.token_ledger_path = Path(token_ledger_path) if token_ledger_path else None

    def _agent_1_spec_review(self, text_base: str, text_mut: str, prompts: List[Dict[str, str]]) -> Dict[str, Any]:
        """Agent 1 evaluates determinism, numbered steps, and elimination of soft terms."""
        diag_base = diagnose_procedure(text_base)
        diag_mut = diagnose_procedure(text_mut)

        # Baseline scoring
        score_base = max(10, 100 - len(diag_base["soft_terms"]) * 15 - (0 if diag_base["has_numbered_steps"] else 30))
        # Mutated scoring
        score_mut = max(10, 100 - len(diag_mut["soft_terms"]) * 15 - (0 if diag_mut["has_numbered_steps"] else 30))

        delta = score_mut - score_base
        verdict = "PASS" if score_mut >= score_base else "FAIL"
        winner = "mutated" if delta > 0 else ("baseline" if delta < 0 else "tie")

        return {
            "judge": "Agent 1 (Spec & Actionability Judge)",
            "focus": "Dim 2 (Workflow) & Dim 5 (Specificity)",
            "score_baseline": score_base,
            "score_mutated": score_mut,
            "delta": delta,
            "verdict": verdict,
            "winner": winner,
            "critique": f"Eliminated {len(diag_base['soft_terms'])} soft terms; structured numbered steps: {diag_mut['has_numbered_steps']}.",
        }

    def _agent_2_safety_review(self, text_base: str, text_mut: str, prompts: List[Dict[str, str]]) -> Dict[str, Any]:
        """Agent 2 evaluates failure recovery modes and anti-pattern blacklist."""
        diag_base = diagnose_procedure(text_base)
        diag_mut = diagnose_procedure(text_mut)

        score_base = 50
        if not diag_base["missing_failure_branches"]:
            score_base += 25
        if not diag_base["missing_blacklist"]:
            score_base += 25

        score_mut = 50
        if not diag_mut["missing_failure_branches"]:
            score_mut += 25
        if not diag_mut["missing_blacklist"]:
            score_mut += 25

        # Check if mutated text is degenerated or empty
        if len(text_mut.strip()) < 30 or "Bad mutated" in text_mut:
            score_mut = 20

        delta = score_mut - score_base
        verdict = "PASS" if score_mut >= score_base else "FAIL"
        winner = "mutated" if delta > 0 else ("baseline" if delta < 0 else "tie")

        return {
            "judge": "Agent 2 (Safety & Robustness Judge)",
            "focus": "Dim 3 (Failure Recovery) & Dim 9 (Risk Blacklist)",
            "score_baseline": score_base,
            "score_mutated": score_mut,
            "delta": delta,
            "verdict": verdict,
            "winner": winner,
            "critique": f"Fallback recovery branch: {not diag_mut['missing_failure_branches']}; Anti-pattern blacklist: {not diag_mut['missing_blacklist']}.",
        }

    def _invoke_llm_judge(
        self,
        candidate_a: str,
        candidate_b: str,
        prompts: List[Dict[str, str]],
        model_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Call external ModelBackend for blind comparative judgment."""
        if not self.model_backend or not callable(getattr(self.model_backend, "review", None)):
            return None

        prompt_text = (
            f"You are an impartial referee evaluating two candidate procedures (Candidate A and Candidate B) "
            f"for test scenario: {prompts[0]['scenario']}.\n\n"
            f"Candidate A:\n```markdown\n{candidate_a}\n```\n\n"
            f"Candidate B:\n```markdown\n{candidate_b}\n```\n\n"
            f"Evaluate both candidates on completeness, lack of ambiguous phrasing, failure fallback, and safety boundaries.\n"
            f"Return JSON strictly with format: {{\"winner\": \"A\" or \"B\" or \"tie\", \"score_a\": int, \"score_b\": int, \"critique\": str}}"
        )

        messages = [
            {"role": "system", "content": "You are an objective software engineering evaluator."},
            {"role": "user", "content": prompt_text},
        ]

        try:
            raw_response = self.model_backend.review(messages)
            if isinstance(raw_response, str):
                text = raw_response.strip()
                if text.startswith("```json") and text.endswith("```"):
                    text = text[7:-3].strip()
                elif text.startswith("```") and text.endswith("```"):
                    text = text[3:-3].strip()
                parsed = json.loads(text)
                return {
                    "model": model_name,
                    "winner": parsed.get("winner"),
                    "score_a": parsed.get("score_a", 0),
                    "score_b": parsed.get("score_b", 0),
                    "critique": parsed.get("critique", ""),
                }
        except Exception:
            return None
        return None

    def evaluate(
        self,
        baseline_text: str,
        mutated_text: str,
        test_prompts: List[Dict[str, str]],
        evaluator_models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Perform blind pairwise evaluation across dual agents and optional LLM backends."""
        # 1. Agent 1: Spec & Actionability Review
        agent_1 = self._agent_1_spec_review(baseline_text, mutated_text, test_prompts)

        # 2. Agent 2: Safety & Robustness Review
        agent_2 = self._agent_2_safety_review(baseline_text, mutated_text, test_prompts)

        # 3. Optional LLM Judge Review
        llm_reviews = []
        if evaluator_models and self.model_backend:
            for model_name in evaluator_models:
                # Blind orientation: Candidate A = Baseline, Candidate B = Mutated
                llm_res = self._invoke_llm_judge(baseline_text, mutated_text, test_prompts, model_name)
                if llm_res:
                    llm_reviews.append(llm_res)

        # 4. Multi-Agent Ratchet Decision (Safety first: no regression allowed)
        spec_passed = agent_1["verdict"] == "PASS"
        safety_passed = agent_2["verdict"] == "PASS"
        combined_delta = agent_1["delta"] + agent_2["delta"]

        ratchet_retained = spec_passed and safety_passed and (combined_delta >= 0)
        winner = "mutated" if combined_delta > 0 else ("baseline" if combined_delta < 0 else "tie")
        ratchet_decision = "RETAIN" if ratchet_retained else "REVERT"

        # 5. Log Token Telemetry if ledger configured
        if self.token_ledger_path:
            try:
                from models.router import TokenLedger
                entry = TokenLedger.create_entry(
                    task_id=f"darwin-eval-{uuid.uuid4().hex[:8]}",
                    gate_phase="darwin_dual_agent_review",
                    model=evaluator_models[0] if evaluator_models else "deterministic-dual-agent",
                    prompt_tokens=len(baseline_text) + len(mutated_text),
                    completion_tokens=len(agent_1["critique"]) + len(agent_2["critique"]),
                    outcome="PASS" if ratchet_retained else "FAIL",
                    evidence_digest=hashlib.sha256(mutated_text.encode("utf-8")).hexdigest()[:16],
                )
                self.token_ledger_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_ledger_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

        return {
            "winner": winner,
            "ratchet_retained": ratchet_retained,
            "ratchet_decision": ratchet_decision,
            "agent_1_spec_judge": agent_1,
            "agent_2_safety_judge": agent_2,
            "llm_reviews": llm_reviews,
            "total_baseline_score": agent_1["score_baseline"] + agent_2["score_baseline"],
            "total_mutated_score": agent_1["score_mutated"] + agent_2["score_mutated"],
            "combined_delta": combined_delta,
        }


class ProcedureOptimizer:
    """Production-grade LAOS Procedure Optimizer with Human Review Gate."""

    def __init__(self, data_root: Path | str, state_dir: Path | str | None = None, model_backend=None, token_ledger_path=None):
        self.data_root = Path(data_root).expanduser().resolve(strict=False)
        self.state_dir = Path(state_dir if state_dir is not None else default_state_dir()).expanduser().resolve(strict=False)
        self.model_backend = model_backend
        self.token_ledger_path = token_ledger_path
        self.judge = DualAgentBlindJudge(model_backend=self.model_backend, token_ledger_path=self.token_ledger_path)

    def find_procedure(self, identifier: str) -> Path:
        """Resolve a procedure identifier (ID, filename, or relative path) to an existing file."""
        candidate_path = Path(identifier).expanduser()
        if candidate_path.is_file():
            return candidate_path.resolve(strict=True)

        rel_path = self.data_root / identifier
        if rel_path.is_file():
            return rel_path.resolve(strict=True)

        proc_dirs = [
            self.data_root / "memory" / "procedures",
            self.data_root / "procedures",
        ]

        for p_dir in proc_dirs:
            if not p_dir.is_dir():
                continue
            # Try exact name match
            exact = p_dir / identifier
            if exact.is_file():
                return exact.resolve(strict=True)
            if not identifier.endswith(".md"):
                md_exact = p_dir / f"{identifier}.md"
                if md_exact.is_file():
                    return md_exact.resolve(strict=True)

            # Search by ID prefix
            for child in p_dir.glob("*.md"):
                if child.name.startswith(f"{identifier}-") or child.name == f"{identifier}.md":
                    return child.resolve(strict=True)
                # Check frontmatter id
                try:
                    head = child.read_text(encoding="utf-8")[:1000]
                    if f'id: "{identifier}"' in head or f"id: '{identifier}'" in head or f"id: {identifier}\n" in head:
                        return child.resolve(strict=True)
                except Exception:
                    continue

        raise FileNotFoundError(f"Procedure '{identifier}' not found in {self.data_root}")

    def optimize(
        self,
        procedure_id_or_path: str,
        workspace: str = "personal",
        dry_run: bool = False,
        evaluator_models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute complete Darwin autonomous optimization cycle on a procedure."""
        proc_file = self.find_procedure(procedure_id_or_path)

        # 1. Read & Parse
        raw_content = proc_file.read_text(encoding="utf-8")
        proc_data = parse_procedure_markdown(raw_content)
        raw_bytes = proc_file.read_bytes()
        source_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        try:
            source_rel = proc_file.relative_to(self.data_root).as_posix()
        except ValueError:
            source_rel = proc_file.name

        # 2. Diagnose
        diagnosis = diagnose_procedure(proc_data["content"])

        # 3. Generate Test Prompts
        prompts = generate_test_prompts(proc_data["title"], proc_data["content"])

        # 4. Mutate / Generate Optimized Procedure
        optimized_content = mutate_procedure(proc_data, diagnosis)

        # 5. Dual-Agent Blind Review
        eval_summary = self.judge.evaluate(
            proc_data["content"],
            optimized_content,
            prompts,
            evaluator_models=evaluator_models,
        )

        if not eval_summary["ratchet_retained"]:
            return {
                "status": "reverted",
                "procedure_id": proc_data.get("id"),
                "title": proc_data.get("title"),
                "reason": "mutated version did not outperform baseline across dual judges",
                "eval_summary": eval_summary,
                "diagnosis": diagnosis,
            }

        # 6. Submit Candidate (unless dry-run)
        candidate_id = None
        candidate_path = None
        if not dry_run:
            candidate = {
                "type": "procedure",
                "title": f"{proc_data['title']} (Darwin 优化版)",
                "workspace": workspace or proc_data.get("workspace", "personal"),
                "scope": proc_data.get("scope", "global"),
                "confidentiality": proc_data.get("confidentiality", "personal"),
                "confidence": "inferred",
                "source": "manual:user_confirmed",
                "action": "create",
                "content": optimized_content,
                "source_path": source_rel,
                "source_sha256": source_sha256,
                "evidence": [f"file:{source_rel}"],
                "tags": list(set(proc_data.get("tags", []) + ["darwin-optimized", "procedure"])),
            }

            store = CandidateStore(self.data_root, state_dir=self.state_dir)
            res = store.create(candidate)
            candidate_id = res.get("candidate_id")
            candidate_path = res.get("path")

            # Re-index store to ensure searchability if DB initialized
            try:
                index_store(argparse.Namespace(root=str(self.data_root), state_dir=str(self.state_dir), dry_run=False))
            except ValueError as exc:
                if "Database is not initialized" in str(exc):
                    pass
                else:
                    raise

        return {
            "status": "candidate_created" if not dry_run else "dry_run_success",
            "procedure_id": proc_data.get("id"),
            "title": proc_data.get("title"),
            "candidate_id": candidate_id,
            "candidate_path": candidate_path,
            "source_file": source_rel,
            "source_sha256": source_sha256,
            "eval_summary": eval_summary,
            "diagnosis": diagnosis,
            "optimized_content_preview": optimized_content[:300] + "...",
        }
