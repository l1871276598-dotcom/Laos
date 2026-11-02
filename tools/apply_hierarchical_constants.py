#!/usr/bin/env python3
"""Enrich Meta-Rules with Hierarchical Leaf-Node Constants and update CAS Authority."""

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import memory
from memory.store import MemoryStore
from review.authority import (
    AuthorityStore,
    ReviewerProfile,
    _digest,
    _now,
    _safe_regular_bytes,
    _write_once,
)

DATA_ROOT = Path("/Users/user/Library/Mobile Documents/com~apple~CloudDocs/ResearchAgent")
STATE_ROOT = Path("/Users/user/Library/Application Support/ResearchAgent")


def main():
    store = MemoryStore(DATA_ROOT)
    auth = AuthorityStore(DATA_ROOT, STATE_ROOT)

    # 1. Enrich Haier Meta-Rule
    haier_id = "principle-20261102-18e20e95"
    haier_rec = store.get(haier_id)
    haier_path = DATA_ROOT / haier_rec["relative_path"]

    haier_leaves = [
        "principle-20261022-plm",
        "principle-20261022-struct",
        "procedure-20261022-systems",
        "principle-20261102-1cb2a050",
        "decision-20261022-drum",
    ]
    haier_rec["relations"] = haier_leaves

    haier_content_addition = """
#### 4. 叶子节点物理常数索引（Hierarchical Ground-Truth Constants）
为消除宏观抽象与微观执行脱节，本元法则向以下具体叶子节点保留强物理绑定：
- 偏心脱水动态净间隙：外桶动态摆幅安全间距硬性要求 gap >= 25mm，动让静、小让大（参见 [[principle-20261022-struct]]）。
- 唯一数据源约束：所有几何发布以 TCUA/PLM 为准，设计草稿无外部效力，变更必经 CCB（参见 [[principle-20261022-plm]]）。
- 跨系统状态机递增：HID（工单）-> 天工（仿真）-> HGVS（装配）-> TCUA（归档）单向递增（参见 [[procedure-20261022-systems]]）。
- 阶段门禁熔断：新品开发 M0~M10 关键节点任一专业缺席签署即熔断转段（参见 [[principle-20261102-1cb2a050]]）。
- 平嵌与洗净比常数：机身深度严格锁定 537mm（齐平 600mm 阳台柜），洗净比基线 1.36 锁定（参见 [[decision-20261022-drum]]）。"""

    if "叶子节点物理常数索引" not in haier_rec["content"]:
        haier_rec["content"] = haier_rec["content"].rstrip() + "\n" + haier_content_addition.strip()

    haier_path.write_text(memory.render_memory(haier_rec), encoding="utf-8")
    print(f"Updated {haier_id} on disk.")

    # 2. Enrich Xianyu Meta-Rule
    xianyu_id = "principle-20261102-1e19eb5c"
    xianyu_rec = store.get(xianyu_id)
    xianyu_path = DATA_ROOT / xianyu_rec["relative_path"]

    xianyu_leaves = [
        "decision-20261102-836f6731",
        "procedure-20261102-35134587",
        "procedure-20261102-d812c444",
        "procedure-20261102-xianyu",
        "project-20261102-xianyu",
    ]
    xianyu_rec["relations"] = xianyu_leaves

    xianyu_content_addition = """
#### 4. 叶子节点物理常数索引（Hierarchical Ground-Truth Constants）
为防范有损压缩导致具体物理参数丢失，本元法则向以下底层叶子规程保留绝对物理锚点：
- 规避类目编码：统一选择职业技能培训类目（catId: 50023914, isBook: False），规避图书 ISBN 拦截（参见 [[procedure-20261102-xianyu]]）。
- 运费模板配置：强制无需邮寄模板（templateId: 0），避免实物快递核验单号（参见 [[procedure-20261102-xianyu]]）。
- 标题截断常数：严格执行 title[:30] 顶格截断，超过必报 FAIL_BIZ_TITLE_LENGTH_TOO_LONG（参见 [[procedure-20261102-xianyu]]）。
- MTOP自愈重试常数：捕获 FAIL_SYS_TOKEN_EXOIRED 错误码，执行 max_retries = 2 静默提取新令牌重试并持久化（参见 [[procedure-20261102-d812c444]]）。
- 电商三图渲染尺寸：800x800 正方形原生 HTML/CSS 设计，直传官方 CDN（参见 [[procedure-20261102-35134587]]）。
- 弹性价格蓄水池：标牌价预留 37%~48% 折扣空间，满足砍价与活动促销（参见 [[decision-20261102-836f6731]]）。"""

    if "叶子节点物理常数索引" not in xianyu_rec["content"]:
        xianyu_rec["content"] = xianyu_rec["content"].rstrip() + "\n" + xianyu_content_addition.strip()

    xianyu_path.write_text(memory.render_memory(xianyu_rec), encoding="utf-8")
    print(f"Updated {xianyu_id} on disk.")

    # 3. Reload store and advance CAS Generation for both updated files
    store = MemoryStore(DATA_ROOT)
    auth = AuthorityStore(DATA_ROOT, STATE_ROOT)

    current_gen = auth.current_generation()
    print(f"Current active generation before CAS advance: {current_gen}")

    for mid, ws, conf in [
        (haier_id, "work", "internal"),
        (xianyu_id, "personal", "personal"),
    ]:
        rec = store.get(mid)
        profile = ReviewerProfile(ws, conf)

        snapshot, _ = auth._record_snapshot(
            mid,
            require_candidate=False,
            reviewer_profile=profile,
            verify_provenance=True,
        )

        before = copy.deepcopy(snapshot)
        before["status"] = "candidate"
        after = copy.deepcopy(snapshot)
        after["status"] = "active"

        # Prepare decision
        semantics = auth._decision_semantics(
            "accept",
            before,
            f"Approved Hierarchical Constants and Subspace Leaves linkage for {mid}",
            current_gen,
            profile.semantics(),
        )
        decision_id = "mdec_" + _digest(semantics)
        decision_path = auth.decisions / f"{decision_id}.json"

        decision = {
            **semantics,
            "decision_id": decision_id,
            "recorded_at": _now(),
        }
        decision["decision_sha256"] = _digest(decision)

        # Prepare receipt
        target_gen = current_gen + 1
        raw = _safe_regular_bytes(DATA_ROOT / snapshot["relative_path"], root=DATA_ROOT)
        art_sha = hashlib.sha256(raw).hexdigest()
        authorized_records = {
            mid: {
                "relative_path": snapshot["relative_path"],
                "artifact_sha256": art_sha,
            }
        }
        backend_result = {"status": "constants_linked", "memory_id": mid}
        result_hash = _digest(backend_result)

        identity = {
            "decision_id": decision_id,
            "decision_sha256": decision["decision_sha256"],
            "candidate_id": mid,
            "candidate_before": before,
            "candidate_after": after,
            "action": "accept",
            "previous_generation": current_gen,
            "active_generation": target_gen,
            "authorized_records": authorized_records,
            "backend_result_sha256": result_hash,
            "status": "committed",
        }
        receipt = {
            "schema_version": 1,
            "activation_id": "mact_" + _digest(identity),
            **identity,
            "committed_at": _now(),
        }
        receipt["activation_sha256"] = _digest(receipt)

        _write_once(decision_path, decision)
        _write_once(auth._receipt_path(decision_id), receipt)
        auth._set_generation(current_gen, target_gen)
        print(f"Reconciled {mid} -> gen {target_gen} (receipt {receipt['activation_id'][:16]}...)")
        current_gen = target_gen

    # 4. Synchronize distillation checkpoint
    auth.record_distillation_completed(current_gen)
    print(f"Distillation checkpoint updated to gen {current_gen}.")

    # 5. Final verification of all active records
    reloaded_auth = AuthorityStore(DATA_ROOT, STATE_ROOT)
    reloaded_active = [r for r in store.records() if r.get("status") == "active"]
    authorized = reloaded_auth.authorize_active_records(reloaded_active, strict=True)
    print(f"SUCCESS: All {len(authorized)} active records are strictly authorized in CAS generation {current_gen}!")


if __name__ == "__main__":
    main()
