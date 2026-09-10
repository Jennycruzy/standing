"""Separate evaluation-arm measurement for Standing and its baselines.

This module intentionally measures prediction artifacts supplied by a runner;
it does not pretend that a grep or model result can be reconstructed from a
case manifest alone. Each arm receives its own metrics and miss list.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evaluation import (
    EvaluationDataset,
    EvaluationDatasetError,
    EvaluationMetrics,
    measure_predictions,
)
from .evaluator import StandingState


BASELINE_ARM_NAMES: tuple[str, ...] = (
    "standing",
    "no-memory",
    "grep",
    "stateless-model",
    "current-docs-only",
)


Prediction = StandingState | str | Mapping[str, Any]


def measure_arms(
    dataset: EvaluationDataset,
    predictions_by_arm: Mapping[str, Mapping[str, Prediction]],
    *,
    required_arms: Sequence[str] = BASELINE_ARM_NAMES,
) -> dict[str, EvaluationMetrics]:
    """Measure named arms independently and require the requested arms.

    Missing arm outputs are an error. This prevents a report from silently
    omitting a weak baseline. The returned mapping is sorted by arm name so
    JSON reports are stable.
    """

    names = tuple(str(name).strip() for name in predictions_by_arm)
    if len(names) != len(set(names)):
        raise EvaluationDatasetError("evaluation arm names must be unique")
    unknown = sorted(set(names) - set(BASELINE_ARM_NAMES))
    if unknown:
        raise EvaluationDatasetError("unknown evaluation arm(s): " + ", ".join(unknown))
    requested = tuple(str(name).strip() for name in required_arms)
    if len(requested) != len(set(requested)):
        raise EvaluationDatasetError("required evaluation arm names must be unique")
    unknown_required = sorted(set(requested) - set(BASELINE_ARM_NAMES))
    if unknown_required:
        raise EvaluationDatasetError(
            "unknown required evaluation arm(s): " + ", ".join(unknown_required)
        )
    missing = sorted(set(requested) - set(names))
    if missing:
        raise EvaluationDatasetError("missing evaluation arm(s): " + ", ".join(missing))
    return {
        name: measure_predictions(dataset, predictions_by_arm[name])
        for name in sorted(names)
    }


def parse_arm_predictions(raw: Any) -> dict[str, Mapping[str, Prediction]]:
    """Validate the JSON shape used by ``evaluate_arms.py``."""

    if not isinstance(raw, Mapping):
        raise EvaluationDatasetError("arm predictions must be an object keyed by arm name")
    result: dict[str, Mapping[str, Prediction]] = {}
    for raw_name, raw_predictions in raw.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise EvaluationDatasetError("evaluation arm names must be non-empty strings")
        if not isinstance(raw_predictions, Mapping):
            raise EvaluationDatasetError(f"predictions for arm {raw_name} must be an object")
        result[raw_name.strip()] = dict(raw_predictions)
    return result
