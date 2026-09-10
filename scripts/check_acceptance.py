"""Check the configured acceptance policy without hiring or writing on-chain."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.acceptance import load_acceptance_policy
from standing.memory import create_memory_store
from standing.reviewer import ReviewerToolError, ReviewerTools


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "policy.json"
VERIFIER_PATH = ROOT / "config" / "verifier.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="sandbox.acme.retention_days")
    parser.add_argument("--approval-id")
    parser.add_argument("--memory-path", type=Path)
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw: Any = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def _condition_binding(condition_key: str) -> dict[str, Any] | None:
    raw = _read_json(VERIFIER_PATH)
    conditions = raw.get("conditions")
    if not isinstance(conditions, dict):
        raise ValueError("verifier.conditions must be an object")
    condition = conditions.get(condition_key)
    if not isinstance(condition, dict):
        raise ValueError(f"verifier condition {condition_key} is missing")
    binding = condition.get("source_binding")
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("verifier source_binding must be an object")
    return binding


def main() -> int:
    args = _arguments()
    store = create_memory_store(
        path=args.memory_path or ROOT / ".standing-memory.db",
        tenant_id="standing",
    )
    try:
        tools = ReviewerTools(store)
        policy = load_acceptance_policy(POLICY_PATH)
        observations = tools.read_observations(args.condition)
        approval_record: dict[str, Any] | None = None
        manual_approval = args.approval_id is not None
        if args.approval_id is not None:
            try:
                stored = store.read_manual_approval(args.approval_id)
            except NotFoundError as error:
                raise ValueError(f"manual approval {args.approval_id} was not found") from error
            body = stored.get("body")
            if not isinstance(body, dict):
                raise ValueError("stored manual approval has no mapping body")
            approval_record = body
        result = tools.check_acceptance(
            args.condition,
            observations,
            manual_approval=manual_approval,
            manual_approval_record=approval_record,
            policy=policy,
            source_binding=_condition_binding(args.condition),
            now_unix=int(time.time()),
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    except (ReviewerToolError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"acceptance check failed: {error}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
