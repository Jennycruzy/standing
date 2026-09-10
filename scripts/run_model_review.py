"""Ask the advisory model which remembered decisions need human review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.memory import create_memory_store
from standing.model_review import (
    ModelReviewError,
    ModelReviewer,
    OpenAIResponsesClient,
    ReviewContext,
)
from standing.reviewer import ReviewerToolError, ReviewerTools


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "model.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="changed paths to review")
    parser.add_argument("--memory-path", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def _read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw: Any = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("model config must contain an object")
    return raw


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _config_values(raw: dict[str, Any]) -> tuple[str, str, str, int]:
    models = raw.get("models")
    if not isinstance(models, dict):
        raise ValueError("model config must contain a models object")
    reviewer_model = _required_string(models.get("reviewer"), "models.reviewer")
    api_key_env = _required_string(raw.get("api_key_env"), "api_key_env")
    endpoint = _required_string(raw.get("responses_endpoint"), "responses_endpoint")
    timeout = raw.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    return reviewer_model, api_key_env, endpoint, timeout


def main() -> int:
    args = _arguments()
    store = create_memory_store(path=args.memory_path or ROOT / ".standing-memory.db")
    try:
        tools = ReviewerTools(store)
        hits = tools.search_decisions(args.paths)
        decisions: list[dict[str, Any]] = []
        for hit in hits:
            body = tools.read_decision(hit.decision_id).body
            candidate = dict(body)
            candidate.setdefault("decision_id", hit.decision_id)
            decisions.append(candidate)
        context = ReviewContext(
            changed_paths=tuple(args.paths),
            candidate_decisions=tuple(decisions),
            boot_changes=tools.read_boot_state().changes,
        )
        reviewer_model, api_key_env, endpoint, timeout = _config_values(
            _read_config(args.config)
        )
        client = OpenAIResponsesClient.from_env(
            env_name=api_key_env,
            endpoint=endpoint,
            timeout_seconds=timeout,
        )
        proposal = ModelReviewer(client, model_id=reviewer_model).review(context)
        print(
            json.dumps(
                {
                    "candidate_decision_count": len(decisions),
                    "proposal": proposal.as_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
    except (ModelReviewError, ReviewerToolError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"model review failed: {error}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
