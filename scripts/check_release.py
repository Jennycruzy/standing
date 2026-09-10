"""Check whether the source-linked evidence is ready for a non-sandbox release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from standing.evaluation import EvaluationDataset, EvaluationDatasetError
from standing.release import ReleaseEvidence, check_release_gates


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("docs/evaluation/cases.json"))
    parser.add_argument(
        "--controlled-scenario-disclosed",
        action="store_true",
        help="confirm that the controlled-scenario disclosure is visible in release materials",
    )
    parser.add_argument(
        "--operator-id",
        action="append",
        default=[],
        help="independent observer operator identity; repeat for each operator",
    )
    parser.add_argument("--minimum-real-cases", type=int, default=3)
    parser.add_argument("--minimum-independent-operators", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    operator_ids = tuple(operator_id.strip() for operator_id in args.operator_id)
    if any(not operator_id for operator_id in operator_ids):
        print("release check failed: --operator-id values must be non-empty", file=sys.stderr)
        return 2
    try:
        dataset = EvaluationDataset.load(args.dataset)
        evidence = ReleaseEvidence.from_dataset(
            dataset,
            controlled_scenario_disclosed=args.controlled_scenario_disclosed,
            independent_operator_ids=operator_ids,
        )
        gate = check_release_gates(
            evidence,
            minimum_real_evaluation_cases=args.minimum_real_cases,
            minimum_independent_operators=args.minimum_independent_operators,
        )
    except (EvaluationDatasetError, OSError, ValueError) as error:
        print(f"release check failed: {error}", file=sys.stderr)
        return 2

    report = {
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "total_case_count": len(dataset.cases),
            "real_case_count": len(dataset.real_cases),
            "reviewed_real_case_count": len(dataset.reviewed_real_cases),
            "pending_real_case_count": len(dataset.pending_real_cases),
            "synthetic_case_count": len(dataset.synthetic_cases),
            "real_vendor_expiry_case_ids": [
                case.case_id for case in dataset.real_vendor_expiry_cases
            ],
        },
        "evidence": evidence.as_dict(),
        "gate": gate.as_dict(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if gate.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
