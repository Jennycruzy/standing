"""Measure all required evaluation arms independently."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.baselines import BASELINE_ARM_NAMES, measure_arms, parse_arm_predictions
from standing.evaluation import EvaluationDataset, EvaluationDatasetError


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--minimum-real-cases", type=int, default=3)
    parser.add_argument(
        "--require-arm",
        action="append",
        dest="required_arms",
        default=None,
        help="arm that must be present; repeat to override the five-arm default",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        dataset = EvaluationDataset.load(args.dataset)
        with args.predictions.open("r", encoding="utf-8") as handle:
            raw: Any = json.load(handle)
        predictions = parse_arm_predictions(raw)
        if args.require_real and dataset.release_case_count() < args.minimum_real_cases:
            raise EvaluationDatasetError(
                f"dataset contains {dataset.release_case_count()} real case(s); "
                f"{args.minimum_real_cases} are required"
            )
        required_arms = BASELINE_ARM_NAMES if args.required_arms is None else tuple(args.required_arms)
        metrics = measure_arms(dataset, predictions, required_arms=required_arms)
    except (EvaluationDatasetError, OSError, json.JSONDecodeError) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    output = {
        "dataset_id": dataset.dataset_id,
        "synthetic_cases": len(dataset.synthetic_cases),
        "real_cases": len(dataset.real_cases),
        "arms": {name: value.as_dict() for name, value in metrics.items()},
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
