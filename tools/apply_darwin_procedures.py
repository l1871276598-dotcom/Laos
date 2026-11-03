#!/usr/bin/env python3
"""tools/apply_darwin_procedures.py — Apply and overwrite active procedures with Darwin-optimized candidates.

Transfers optimized 4-section structured contents and anti-pattern blacklists
into the canonical active procedures, marks updated timestamp, tags darwin-optimized,
removes candidate files, and re-indexes SQLite store.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory import (
    atomic_write_text,
    collect_validated_records,
    default_state_dir,
    index_store,
    parse_front_matter,
    render_memory,
)


def apply_darwin_procedures(data_root: Path | str, state_dir: Path | str | None = None) -> list[dict]:
    root = Path(data_root).expanduser().resolve(strict=True)
    if state_dir is None:
        state_dir = default_state_dir()
    state_dir = Path(state_dir).expanduser().resolve(strict=False)

    proc_dir = root / "memory" / "procedures"
    candidate_files = sorted(proc_dir.glob("*-Darwin-优化版.md"))
    if not candidate_files:
        print("No Darwin candidate procedures found.")
        return []

    today = date.today().isoformat()
    applied_records = []

    for cand_file in candidate_files:
        cand_record, cand_errors = parse_front_matter(cand_file)
        if cand_errors:
            raise ValueError(f"Candidate {cand_file.name} has frontmatter errors: {cand_errors}")

        source_path_rel = cand_record.get("source_path")
        if not source_path_rel:
            raise ValueError(f"Candidate {cand_file.name} missing source_path")

        target_file = (root / source_path_rel).resolve()
        if not target_file.is_file():
            raise FileNotFoundError(f"Target procedure file {source_path_rel} not found")

        target_record, target_errors = parse_front_matter(target_file)
        if target_errors:
            raise ValueError(f"Target {target_file.name} has frontmatter errors: {target_errors}")

        # Update target with Darwin optimization
        target_record["content"] = cand_record["content"]
        target_record["updated"] = today
        tags = list(set(target_record.get("tags", []) + ["darwin-optimized"]))
        tags.sort()
        target_record["tags"] = tags

        # Render and write back atomically
        rendered = render_memory(target_record)
        atomic_write_text(target_file, rendered)

        # Unlink candidate file
        cand_file.unlink()

        applied_records.append({
            "target_id": target_record["id"],
            "target_title": target_record["title"],
            "target_path": str(target_file.relative_to(root)),
            "applied_candidate": cand_file.name,
        })
        print(f"  ✅ Applied to: {target_record['id']} ({target_record['title']})")

    # Re-index store
    print("\nRe-indexing memory store...")
    index_store(argparse.Namespace(root=str(root), state_dir=str(state_dir), dry_run=False))

    # Validate store
    print("Validating store integrity...")
    _, valid_records, errors, warnings = collect_validated_records(root)
    if errors:
        raise ValueError(f"Validation failed after apply: {errors}")
    print(f"Validation successful: {len(valid_records)} files valid, 0 errors, {warnings} warnings.")

    return applied_records


def main():
    parser = argparse.ArgumentParser(description="Apply Darwin Procedure Candidates to canonical active procedures")
    parser.add_argument("--root", default="/Users/user/Library/Mobile Documents/com~apple~CloudDocs/ResearchAgent", help="LAOS data root path")
    parser.add_argument("--state-dir", default=None, help="LAOS state directory")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  🚀 Applying Darwin Optimized Procedures to Active Store")
    print("=" * 60)
    applied = apply_darwin_procedures(args.root, args.state_dir)
    print("=" * 60)
    print(f"Successfully applied and activated {len(applied)} Darwin procedures.")


if __name__ == "__main__":
    main()
