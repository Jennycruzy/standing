"""Measure one prediction arm against a source-linked Standing dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.evaluation import EvaluationDataset, EvaluationDatasetError, measure_predictions


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--minimum-real-cases", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        dataset = EvaluationDataset.load(args.dataset)
        with args.predictions.open("r", encoding="utf-8") as handle:
            raw_predictions: Any = json.load(handle)
        if not isinstance(raw_predictions, dict):
            raise EvaluationDatasetError("predictions file must contain an object keyed by case ID")
        if args.require_real and dataset.release_case_count() < args.minimum_real_cases:
            raise EvaluationDatasetError(
                f"dataset contains {dataset.release_case_count()} real case(s); "
                f"{args.minimum_real_cases} are required"
            )
        metrics = measure_predictions(dataset, raw_predictions)
    except (EvaluationDatasetError, OSError, json.JSONDecodeError) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(metrics.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
