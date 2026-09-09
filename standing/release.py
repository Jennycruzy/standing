"""Release-readiness gates for evidence and evaluation quality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evaluation import EvaluationDataset


@dataclass(frozen=True)
class ReleaseEvidence:
    """Evidence claims required before presenting a non-demo release."""

    controlled_demo_disclosed: bool
    real_vendor_expiry_present: bool
    real_evaluation_case_count: int
    independent_operator_ids: tuple[str, ...]

    @classmethod
    def from_dataset(
        cls,
        dataset: EvaluationDataset,
        *,
        controlled_demo_disclosed: bool,
        real_vendor_expiry_present: bool,
        independent_operator_ids: tuple[str, ...],
    ) -> ReleaseEvidence:
        """Build release evidence from the dataset's validated real-case count."""

        return cls(
            controlled_demo_disclosed=controlled_demo_disclosed,
            real_vendor_expiry_present=real_vendor_expiry_present,
            real_evaluation_case_count=dataset.release_case_count(),
            independent_operator_ids=independent_operator_ids,
        )


@dataclass(frozen=True)
class ReleaseGateResult:
    """The deterministic result of the release gates."""

    ready: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reasons": list(self.reasons),
        }


def check_release_gates(
    evidence: ReleaseEvidence,
    *,
    minimum_real_evaluation_cases: int = 3,
    minimum_independent_operators: int = 2,
) -> ReleaseGateResult:
    """Require real, disclosed evidence before a release can claim readiness."""

    if minimum_real_evaluation_cases <= 0:
        raise ValueError("minimum_real_evaluation_cases must be positive")
    if minimum_independent_operators <= 0:
        raise ValueError("minimum_independent_operators must be positive")
    if evidence.real_evaluation_case_count < 0:
        raise ValueError("real_evaluation_case_count must be non-negative")

    reasons: list[str] = []
    if not evidence.controlled_demo_disclosed:
        reasons.append("The controlled-demo disclosure is not visible in the release evidence.")
    if not evidence.real_vendor_expiry_present:
        reasons.append("A real vendor-expiry case is required before release.")
    if evidence.real_evaluation_case_count < minimum_real_evaluation_cases:
        reasons.append(
            f"Only {evidence.real_evaluation_case_count} real evaluation case(s) are present; "
            f"the release requires {minimum_real_evaluation_cases}."
        )
    operator_ids = tuple(sorted(set(evidence.independent_operator_ids)))
    if len(operator_ids) < minimum_independent_operators:
        reasons.append(
            f"Only {len(operator_ids)} independent operator identity(ies) are present; "
            f"the release requires {minimum_independent_operators}."
        )
    return ReleaseGateResult(not reasons, tuple(reasons))
