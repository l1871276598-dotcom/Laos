# -*- coding: utf-8 -*-
"""Feishu Interactive Card Delivery Channel & Human-Gate Callback Adapter."""

import base64
import hashlib
import hmac
import json
import time
import urllib.request
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from harness.approval_card import ApprovalCard
from harness.decision_ledger import DecisionLedger, DecisionRecord, DecisionType


class ApprovalAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ADD_TO_NEGATIVE_LEDGER = "ADD_TO_NEGATIVE_LEDGER"


class FeishuCardBuilder:
    """Renders LAOS ApprovalCard into the Feishu Interactive Message Card JSON Schema."""

    @staticmethod
    def build_card_payload(card: ApprovalCard) -> Dict[str, Any]:
        rec_upper = str(card.recommendation).upper()
        if card.risk_category or "REJECT" in rec_upper:
            template = "red"
        elif "APPROVE" in rec_upper:
            template = "blue"
        else:
            template = "orange"

        entities_str = (
            ", ".join(f"`{e}`" for e in card.affected_entities)
            if card.affected_entities
            else "None"
        )
        risk_line = f"⚠️ **高危类别**: `{card.risk_category}`\n" if card.risk_category else ""

        markdown_content = (
            f"**流水线 ID**: `{card.pipeline_id}` | **事件源**: `{card.event_source}`\n"
            f"{risk_line}\n"
            f"### 拟执行动作\n"
            f"{card.action_summary}\n\n"
            f"**受影响实体**: {entities_str}\n\n"
            f"### 推荐决策与理由\n"
            f"- **推荐裁决**: `{card.recommendation}`\n"
            f"- **理由阐述**: {card.rationale}\n"
        )

        actions = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🟢 批红同意 (Approve)"},
                "type": "primary",
                "value": {
                    "action": "APPROVE",
                    "proposal_id": card.pipeline_id,
                    "proposal_summary": card.action_summary,
                },
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔴 驳回否决 (Reject)"},
                "type": "danger",
                "value": {
                    "action": "REJECT",
                    "proposal_id": card.pipeline_id,
                    "proposal_summary": card.action_summary,
                },
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "⛔ 加入《定了不做》"},
                "type": "default",
                "value": {
                    "action": "ADD_TO_NEGATIVE_LEDGER",
                    "proposal_id": card.pipeline_id,
                    "proposal_summary": card.action_summary,
                    "reason": card.rationale,
                },
            },
        ]

        return {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True,
                    "enable_forward": False,
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🚨 [LAOS Human Gate] {card.title}",
                    },
                    "template": template,
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": markdown_content,
                    },
                    {"tag": "hr"},
                    {
                        "tag": "action",
                        "actions": actions,
                    },
                ],
            },
        }


class FeishuChannel:
    """Feishu Webhook Messenger and Interactive Card Callback Consumer."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.webhook_url = webhook_url
        self.secret = secret
        self.dry_run = dry_run or (webhook_url is None)
        self.builder = FeishuCardBuilder()

    @staticmethod
    def calculate_signature(timestamp: int, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def send_approval_card(self, card: ApprovalCard) -> Dict[str, Any]:
        payload = self.builder.build_card_payload(card)

        if self.secret:
            ts = int(time.time())
            payload["timestamp"] = str(ts)
            payload["sign"] = self.calculate_signature(ts, self.secret)

        if self.dry_run or not self.webhook_url:
            return {
                "status": "dry_run_success",
                "payload": payload,
            }

        req_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=self.webhook_url,
            data=req_data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8")
            return {
                "status": "success",
                "http_code": resp.status,
                "response": json.loads(resp_body) if resp_body else {},
            }

    def handle_callback(
        self,
        callback_payload: Dict[str, Any],
        ledger: Optional[DecisionLedger] = None,
    ) -> Tuple[str, Optional[DecisionRecord]]:
        action_dict = callback_payload.get("action", {})
        val = action_dict.get("value", {})
        action_name = val.get("action", "UNKNOWN")
        proposal_id = val.get("proposal_id", "")
        proposal_summary = val.get("proposal_summary", "")
        reason = val.get("reason", "Decided via Feishu interactive card.")

        record: Optional[DecisionRecord] = None
        if ledger is not None:
            if action_name == "APPROVE":
                record = DecisionRecord(
                    decision_id=f"dir-{proposal_id}",
                    decision_type=DecisionType.APPROVED_DIRECTIVE,
                    topic=proposal_summary or proposal_id,
                    rationale=reason,
                )
                ledger.record_decision(record)
            elif action_name in ("REJECT", "ADD_TO_NEGATIVE_LEDGER"):
                record = DecisionRecord(
                    decision_id=f"neg-{proposal_id}",
                    decision_type=DecisionType.NEGATIVE_DIRECTIVE,
                    topic=proposal_summary or proposal_id,
                    rationale=reason,
                    prohibited_patterns=[proposal_summary or proposal_id],
                )
                ledger.record_decision(record)

        return action_name, record
