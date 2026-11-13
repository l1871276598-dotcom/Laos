import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ApprovalCard:
    pipeline_id: str
    title: str
    event_source: str
    action_summary: str
    recommendation: str
    rationale: str
    affected_entities: List[str] = field(default_factory=list)
    risk_category: Optional[str] = None
    card_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_markdown(self) -> str:
        risk_badge = f"⚠️ **高危类别**: `{self.risk_category}`\n" if self.risk_category else ""
        entities = ", ".join(f"`{e}`" for e in self.affected_entities) if self.affected_entities else "None"

        return (
            f"# 🚨 [LAOS Human Gate] {self.title}\n\n"
            f"> **流水线 ID**: `{self.pipeline_id}` | **事件源**: `{self.event_source}`\n"
            f"{risk_badge}\n"
            f"### 拟执行动作\n"
            f"{self.action_summary}\n\n"
            f"**受影响实体**: {entities}\n\n"
            f"### 推荐决策与理由\n"
            f"- **推荐裁决**: {self.recommendation}\n"
            f"- **理由阐述**: {self.rationale}\n\n"
            f"---\n"
            f"**请人类架构师做出最终裁决**:\n"
            f"- `[1] 批准 (Approve)` -> 物化为代际《定的事》并恢复流水线\n"
            f"- `[2] 拒绝 (Reject)` -> 物化为代际《定了不做》并即刻熔断\n"
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
