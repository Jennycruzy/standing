"""Record an explicit human approval for the current evidence ledger."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.memory import create_memory_store
from standing.reviewer import ReviewerTools


ROOT = Path(__file__).resolve().parents[1]


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
        print(
            json.dumps(
                {
                    "approval": recorded.as_dict(),
                    "observation_count": len(observations),
                    "evidence_fingerprint": digest,
                },
                indent=2,
                sort_keys=True,
            )
        )
    except (ValueError, OSError) as error:
        print(f"approval failed: {error}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
