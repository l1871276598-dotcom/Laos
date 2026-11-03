# LAOS 生产级 Agent Harness 顶层架构蓝图

> **状态**：已批准（Approved by Author）  
> **日期**：2026-11-03  
> **核心范式**：卡兹克实战范式（事件驱动调度 + 五步物理流水线 + 决策记忆永不问第二遍）  
> **关联 ADR**：`decision-20261103-harness-blueprint`  
> **关联合同/元法则**：`principle-20261103-harness-invariants`  

---

## 一、系统背景与核心矛盾

### 1. 核心矛盾定义
在传统的单会话/交互式 Agent 模式（如人工打开终端窗口使用 Claude Code 或 Codex）中，存在严重的**注意力瓶颈**与**并发冲突**：
1. **注意力瓶颈（The Attention Bottleneck）**：单任务上限取决于基础大模型能力，但多任务上限受制于人类注意力（“一个人通常只能跟进 3~5 个活跃会话”）。
2. **缺乏客观物理真理（Lack of Ground-Truth Witness）**：纯文本离线评审容易陷入模型深层共谋与陈词滥调（Platitude Pathology），缺乏由真实代码执行、单测套件通过率、线上版本探针返回构成的“客观第三法官”。
3. **意图摇摆与重复决策摩擦（Decision Fatigue & Intent Oscillation）**：多 Agent 协作时缺乏不可变决策账本，导致不同 Agent、不同会话对同一已决事项反复询问人类，侵蚀工程执行力。

### 2. 顶层设计原则
1. **任务起点从人身上剥离**：以事件（Event）为系统起点，调度中枢自主唤醒 Agent，人类退居为“明代内阁票拟 + 皇帝批红”的一键决策者。
2. **物理验证先于主观声明**：代码交付必须通过五步机械流水线，以不可伪造的沙箱退出码与探针为验收依据。
3. **决策一次判定，全局终局**：人类作出的决策自动沉淀为不可变 CAS 记忆，跨模型、跨会话永不再问第二遍。

---

## 二、三层系统架构全景

```
                    ┌────────────────────────────────────────────────────────┐
                    │       LAOS 生产级 Agent Harness 架构全景                │
                    └────────────────────────────────────────────────────────┘
                                                 │
       ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
       ▼                                         ▼                                         ▼
【1. 自动化调度中台】                     【2. 物理验证与 CI 中台】                 【3. 人机决策终局网关】
 (Event & Dispatch Center)               (Physical 5-Step Pipeline)               (Human-Gate & Ledger)
 - Webhook / Cron 统一信封                 - 步1: 异构模型对抗审查 (<=3轮,禁挑风格)   - 飞书 / 终端交互卡片
 - 幂等哈希去重 (Idempotency)              - 步2: 瞬态隔离环境全量测试/构建          - 高危动作拦截白名单 (Kill Gate)
 - rules.json 规则路由 (Agent/Skill/模型)   - 步3: GitHub 受保护分支原子合并         - 《已定决策》《定了不做》
 - 本地 Worker 50s 长轮询 (无公网暴露)      - 步4: 隔离发布受控执行                  - 写入不可变 authority_generation
                                           - 步5: 线上真理探针核实 (Ground-Truth)    - 跨 Agent 永久继承
```

---

## 三、四大核心模块规范

### 1. 自动化调度中台 (Event & Dispatch Center)
- **统一事件信封（Event Envelope）**：
  ```json
  {
    "event_id": "evt-20261103-xxxx",
    "source": "webhook:github_issue | cron:daily_cleanup | alert:sentry",
    "event_type": "issue.created | schedule.tick | system.error",
    "target": "laos-ws/codex#102",
    "summary": "Fix connection timeout in memory vector search",
    "context_url": "https://github.com/...",
    "dedup_key": "sha256(source + event_type + target)"
  }
  ```
- **规则路由表（`rules.json`）**：
  - 声明事件类型 $\to$ 目标机器（Host） $\to$ 绑定 Agent（Codex/Claude） $\to$ 挂载规程/Skill $\to$ 推理等级（Low/High/Max）。
  - 并发与租约控制：针对同一 `target`，同一时刻仅允许 1 个活动 Worker 持有写租约，杜绝脏写。
- **本地 Worker 长轮询（Long-Polling Worker）**：
  - 本地 Mac 运行轻量 Worker 守护进程，向云端信箱发起最长 50 秒的 HTTP 长轮询取活，无需将本地开发机暴露到公网。

### 2. 执行与反熵中台 (Execution & Anti-Entropy Janitor)
- **Skill/Procedure 解耦承载**：
  - 任务细节与业务规则封装于 LAOS 五段式规程（`memory/procedures/`）或专属 Skill 中，Agent 仅作为解释执行器。
- **例行反熵大扫除机制（Anti-Entropy Janitor）**：
  - 定时调度反熵 Agent，自动修剪过期的临时补丁代码、重复规程碎片与失效 Handoff，维持代码库与记忆库的熵值单调不增。

### 3. 五步物理物化流水线 (CI & Ground-Truth Verification)
- **步 1：异构模型受控对抗审查（Adversarial Review）**：
  - 角色分离：Claude 编写代码，Codex 独立审查（或反之）；
  - 防内耗硬性护栏：**轮次严格限制 $\le 3$ 轮；只读沙箱、无网络、无凭据；强制注入模板“仅审查致命崩溃、数据损坏与安全漏洞，绝对禁止挑代码风格”**。
- **步 2：瞬态隔离环境机械检查（Deterministic Checks）**：
  - 启动隔离瞬态环境，执行类型检查（Typecheck）、全量单元测试（100% Pass）、编译构建与数据库“只增不改”约束。
- **步 3：GitHub 受保护分支原子合并（Gate-Protected Merge）**：
  - 审查与单测双 PASS 后自动合并，未通过者在分支层面物理锁死。
- **步 4：受控环境发布（Controlled Deployment）**。
- **步 5：线上真理探针核实（Post-Deploy Ground-Truth Verification）**：
  - 探针向线上环境发起健康与版本核对，确认新版本生效后，向系统输出权威见证（Witness W），作为任务关闭的唯一客观判据。

### 4. 人机决策网关与记忆终局 (Human Gate & Memory Ledger)
- **严格最小化推向人类的决策范围（Kill Gate Whitelist）**：
  - 仅在触发 Section 5 诚实边界或高危不可逆操作时，才推向人类终端（飞书互动卡片/终端）：
    1. 删除生产数据 / 清空存储；
    2. 核心服务停服或重启；
    3. 产生不可逆资金或算力费用消耗；
    4. 对外正式发布声称或法务公开发言；
    5. 修改核心业务/产品顶层方向；
    6. 新建、轮换或撤销核心密钥与证书；
    7. 修改用户角色、访问权限与系统信任根。
- **决策终局记录（《已定决策》与《定了不做》）**：
  - 人类的每一次批红或拒绝，直接由 Harness 封装为 `decision-YYYYMMDD-...` 权威记忆记录；
  - 记录必须携带人类原话、时间戳、上下文 Hash，并递增 `authority_generation` CAS 代际；
  - 后续所有模型调用 `laos_context_build` 时自动载入，**永远不再向人类发起二次提问**。
