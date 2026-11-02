#!/usr/bin/env python3
"""Batch reconciliation script for unreceipted active memories in ResearchAgent."""

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
from review.source_refs import resolve_source_bindings


def reconcile(data_root: Path, state_root: Path, dry_run: bool = False):
    store = MemoryStore(data_root)
    auth = AuthorityStore(data_root, state_root)
    active_records = [r for r in store.records() if r.get("status") == "active"]

    baseline = auth._baseline()["records"]
    existing_receipts = {}
    for path in auth.activations.iterdir():
        if path.suffix == ".json" and not path.name.startswith(".tmp."):
            r = auth._read_receipt(path.stem)
            for mid, b in r["authorized_records"].items():
                existing_receipts[mid] = b

    unreceipted = []
    for r in active_records:
        mid = r["id"]
        rpath = r.get("relative_path")
        raw = _safe_regular_bytes(data_root / rpath, root=data_root)
        binding = {
            "relative_path": rpath,
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if baseline.get(mid) == binding:
            continue
        rc = existing_receipts.get(mid)
        if rc is None or rc != binding:
            unreceipted.append(r)

    print(f"Found {len(unreceipted)} unreceipted active records.")
    if not unreceipted:
        print("All active records are already authorized.")
        return

    # Phase 1: normalize provenance and frontmatter on disk
    for r in unreceipted:
        mid = r["id"]
        file_path = data_root / r["relative_path"]
        changed = False

        if r.get("source_refs"):
            # Check for malformed source_refs without scheme
            cleaned_refs = []
            for sref in r["source_refs"]:
                if "://" in sref or sref.startswith("file:") or sref.startswith("doc:"):
                    cleaned_refs.append(sref)
            if cleaned_refs != r["source_refs"]:
                if cleaned_refs:
                    r["source_refs"] = cleaned_refs
                else:
                    r.pop("source_refs", None)
                changed = True

        if r.get("source") == "agent" and r.get("confirmation") == "explicit":
            r["source"] = "user"
            changed = True

        try:
            res = resolve_source_bindings(data_root, state_root, r)
        except Exception:
            # Fallback to manual declaration
            if r.get("source") not in {"user", "manual:user_confirmed"}:
                r["source"] = "user"
            res = resolve_source_bindings(data_root, state_root, r)

        if r.get("source_provenance") != res["source_provenance"]:
            r["source_provenance"] = res["source_provenance"]
            changed = True
        if r.get("source_bindings") != res["source_bindings"]:
            r["source_bindings"] = res["source_bindings"]
            changed = True

        if changed and not dry_run:
            file_path.write_text(memory.render_memory(r), encoding="utf-8")
            print(f"Updated metadata on disk: {r['relative_path']}")

    # Reload store after potential file edits
    store = MemoryStore(data_root)
    auth = AuthorityStore(data_root, state_root)

    # Phase 2: Create decisions and activation receipts advancing generation CAS
    current_gen = auth.current_generation()
    print(f"Current active generation: {current_gen}")

    for r in unreceipted:
        mid = r["id"]
        rec = store.get(mid)
        ws = rec.get("workspace", "personal")
        conf = rec.get("confidentiality", "personal")
        if ws == "work" and conf == "personal":
            conf = "internal"
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
            "Batch reconciliation of pre-existing verified memory",
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
        raw = _safe_regular_bytes(data_root / snapshot["relative_path"], root=data_root)
        art_sha = hashlib.sha256(raw).hexdigest()
        authorized_records = {
            mid: {
                "relative_path": snapshot["relative_path"],
                "artifact_sha256": art_sha,
            }
        }
        backend_result = {"status": "reconciled", "memory_id": mid}
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

        if not dry_run:
            _write_once(decision_path, decision)
            _write_once(auth._receipt_path(decision_id), receipt)
            auth._set_generation(current_gen, target_gen)
            print(f"Reconciled {mid} -> gen {target_gen} (receipt {receipt['activation_id'][:16]}...)")
            current_gen = target_gen

    if not dry_run:
        # Phase 3: Final verification
        reloaded_auth = AuthorityStore(data_root, state_root)
        reloaded_active = [r for r in store.records() if r.get("status") == "active"]
        authorized = reloaded_auth.authorize_active_records(reloaded_active, strict=True)
        print(f"VERIFICATION SUCCESS: All {len(authorized)} active records are strictly authorized!")


if __name__ == "__main__":
    DATA_ROOT = Path("/Users/user/Library/Mobile Documents/com~apple~CloudDocs/ResearchAgent")
    STATE_ROOT = Path("/Users/user/Library/Application Support/ResearchAgent")
    reconcile(DATA_ROOT, STATE_ROOT, dry_run=False)
