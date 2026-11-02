#!/usr/bin/env python3
"""Inspect or update the LAOS Meta-Rule Distillation generation threshold status."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from review.authority import AuthorityStore

DATA_ROOT = Path("/Users/user/Library/Mobile Documents/com~apple~CloudDocs/ResearchAgent")
STATE_ROOT = Path("/Users/user/Library/Application Support/ResearchAgent")


def main():
    parser = argparse.ArgumentParser(description="Check or update LAOS meta-rule distillation trigger.")
    parser.add_argument("--data-root", default=str(DATA_ROOT))
    parser.add_argument("--state-dir", default=str(STATE_ROOT))
    parser.add_argument("--interval", type=int, default=None, help="Set trigger interval (delta generation)")
    parser.add_argument("--record-completed", action="store_true", help="Record distillation completed at current generation")
    args = parser.parse_args()

    auth = AuthorityStore(Path(args.data_root), Path(args.state_dir))

    if args.interval is not None:
        updated = auth.set_distillation_policy(interval=args.interval)
        print(f"Updated distillation policy interval to {updated['interval']}.")

    if args.record_completed:
        recorded = auth.record_distillation_completed()
        print(f"Recorded distillation completed at generation {recorded['last_distilled_generation']}.")

    status = auth.check_distillation_due()
    next_trigger = status["last_distilled_generation"] + status["interval"]
    summary = {
        "distillation_due": status["due"],
        "current_active_generation": status["current_generation"],
        "last_distilled_generation": status["last_distilled_generation"],
        "generation_delta": status["delta"],
        "interval_threshold": status["interval"],
        "next_trigger_generation": next_trigger,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
