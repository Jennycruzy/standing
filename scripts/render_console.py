"""Render a read-only Standing decision console from local memory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.console import render_console_html
from standing.evaluation import EvaluationDataset
from standing.memory import create_memory_store
from standing.release import ReleaseEvidence, check_release_gates
from standing.reviewer import ReviewerToolError, ReviewerTools


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--as-of", type=int)
    parser.add_argument("--memory-path", type=Path)
    parser.add_argument("--dataset", type=Path, default=Path("docs/evaluation/cases.json"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    store = create_memory_store(path=args.memory_path)
    try:
        snapshot = ReviewerTools(store).read_decision_at(args.decision_id, as_of=args.as_of)
        dataset = EvaluationDataset.load(args.dataset)
        evidence = ReleaseEvidence.from_dataset(
            dataset,
            controlled_scenario_disclosed=True,
            real_vendor_expiry_present=False,
            independent_operator_ids=(),
        )
        html = render_console_html(
            snapshot,
            controlled_scenario_disclosed=True,
            release_gate=check_release_gates(evidence),
        )
    except (ReviewerToolError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"console render failed: {error}", file=sys.stderr)
        return 2
    finally:
        store.close()
    if args.output is None:
        print(html)
    else:
        args.output.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
