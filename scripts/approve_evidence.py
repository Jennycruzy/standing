"""Record an explicit human approval for the current evidence ledger."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.acceptance import load_acceptance_policy
from standing.memory import create_memory_store
from standing.reviewer import ReviewerToolError, ReviewerTools


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "policy.json"
VERIFIER_PATH = ROOT / "config" / "verifier.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="sandbox.demo.retention_days")
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--memory-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    store = create_memory_store(
        path=args.memory_path or ROOT / ".standing-memory.db",
        tenant_id="standing-demo",
    )
    try:
        tools = ReviewerTools(store)
        observations = tools.read_observations(args.condition)
        if not observations:
            raise ValueError("no observations are available to approve")
        digest = evidence_fingerprint(args.condition, observations)
        approval = issue_manual_approval(
            args.approval_id,
            args.condition,
            approved_by=args.approved_by,
            approver_role="human",
            approved_at=int(time.time()),
            evidence_digest=digest,
            reason=args.reason,
        )
        recorded = tools.record_manual_approval(approval)
        policy = load_acceptance_policy(POLICY_PATH)
        acceptance = tools.check_acceptance(
            args.condition,
            observations,
            manual_approval=True,
            manual_approval_record=recorded.as_dict(),
            policy=policy,
            source_binding=_condition_binding(args.condition),
            now_unix=int(time.time()),
        )
        promotion = None
        if acceptance.accepted:
            promotion = tools.promote_acceptance(
                args.condition,
                acceptance,
                observations,
                accepted_at=int(time.time()),
            )
        print(
            json.dumps(
                {
                    "approval": recorded.as_dict(),
                    "observation_count": len(observations),
                    "evidence_fingerprint": digest,
                    "acceptance": acceptance.as_dict(),
                    "promotion": None if promotion is None else promotion.as_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
    except (ValueError, OSError, ReviewerToolError, json.JSONDecodeError) as error:
        print(f"approval failed: {error}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


def _condition_binding(condition_key: str) -> dict[str, Any] | None:
    with VERIFIER_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("conditions"), dict):
        raise ValueError("verifier.conditions must be an object")
    condition = raw["conditions"].get(condition_key)
    if not isinstance(condition, dict):
        raise ValueError(f"verifier condition {condition_key} is missing")
    binding = condition.get("source_binding")
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("verifier source_binding must be an object")
    return binding


if __name__ == "__main__":
    raise SystemExit(main())
