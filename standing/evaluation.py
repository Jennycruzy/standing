"""Source-linked evaluation datasets and deterministic measurement."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .evaluator import StandingState


class EvaluationDatasetError(ValueError):
    """Raised when an evaluation case cannot be linked to auditable sources."""


_SOURCE_TYPES = frozenset({"vendor_history", "repository_history", "published_record"})
_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_DISALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "example.com", "example.org"})


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationDatasetError(f"{label} must be a non-empty string")
    return value.strip()


def _https_url(value: Any, label: str) -> str:
    url = _required_string(value, label)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise EvaluationDatasetError(f"{label} must be an HTTPS URL without embedded credentials")
    hostname = parsed.hostname
    if hostname is None or hostname.lower() in _DISALLOWED_HOSTS:
        raise EvaluationDatasetError(f"{label} must point to a public source host")
    return url


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvaluationDatasetError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class EvaluationCase:
    """One source-linked real-world decision and its published ground truth."""

    case_id: str
    repository: str
    decision_url: str
    decision_ref: str
    ground_truth_url: str
    ground_truth_source_type: str
    ground_truth_effective_at: int
    captured_at: int
    source_sha256: str
    expected_state: StandingState
    synthetic: bool
    notes: str | None = None

    def __post_init__(self) -> None:
        _required_string(self.case_id, "case_id")
        _required_string(self.repository, "repository")
        _https_url(self.decision_url, "decision_url")
        _required_string(self.decision_ref, "decision_ref")
        _https_url(self.ground_truth_url, "ground_truth_url")
        if self.ground_truth_source_type not in _SOURCE_TYPES:
            raise EvaluationDatasetError(
                f"ground_truth_source_type must be one of {sorted(_SOURCE_TYPES)}"
            )
        _nonnegative_int(self.ground_truth_effective_at, "ground_truth_effective_at")
        _nonnegative_int(self.captured_at, "captured_at")
        if not _HEX_DIGEST.fullmatch(self.source_sha256):
            raise EvaluationDatasetError("source_sha256 must be a 64-character SHA-256 digest")
        if not isinstance(self.expected_state, StandingState):
            raise EvaluationDatasetError("expected_state must be a StandingState")
        if not isinstance(self.synthetic, bool):
            raise EvaluationDatasetError("synthetic must be true or false")
        if self.notes is not None:
            _required_string(self.notes, "notes")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvaluationCase:
        """Parse one case; ``synthetic`` is required rather than inferred."""

        if not isinstance(raw, Mapping):
            raise EvaluationDatasetError("evaluation case must be a mapping")
        state_raw = _required_string(raw.get("expected_state"), "expected_state")
        try:
            state = StandingState(state_raw)
        except ValueError as error:
            raise EvaluationDatasetError(f"unknown expected_state {state_raw}") from error
        source_type = _required_string(raw.get("ground_truth_source_type"), "ground_truth_source_type")
        return cls(
            _required_string(raw.get("case_id"), "case_id"),
            _required_string(raw.get("repository"), "repository"),
            _https_url(raw.get("decision_url"), "decision_url"),
            _required_string(raw.get("decision_ref"), "decision_ref"),
            _https_url(raw.get("ground_truth_url"), "ground_truth_url"),
            source_type,
            _nonnegative_int(raw.get("ground_truth_effective_at"), "ground_truth_effective_at"),
            _nonnegative_int(raw.get("captured_at"), "captured_at"),
            _required_string(raw.get("source_sha256"), "source_sha256"),
            state,
            _required_bool(raw.get("synthetic"), "synthetic"),
            raw.get("notes") if raw.get("notes") is None else _required_string(raw.get("notes"), "notes"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "repository": self.repository,
            "decision_url": self.decision_url,
            "decision_ref": self.decision_ref,
            "ground_truth_url": self.ground_truth_url,
            "ground_truth_source_type": self.ground_truth_source_type,
            "ground_truth_effective_at": self.ground_truth_effective_at,
            "captured_at": self.captured_at,
            "source_sha256": self.source_sha256,
            "expected_state": self.expected_state.value,
            "synthetic": self.synthetic,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EvaluationDataset:
    """A validated collection of source-linked evaluation cases."""

    dataset_id: str
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self) -> None:
        _required_string(self.dataset_id, "dataset_id")
        identifiers = [case.case_id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise EvaluationDatasetError("evaluation case IDs must be unique")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvaluationDataset:
        if not isinstance(raw, Mapping):
            raise EvaluationDatasetError("evaluation dataset must be a mapping")
        raw_cases = raw.get("cases")
        if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
            raise EvaluationDatasetError("evaluation dataset cases must be a list")
        cases = tuple(EvaluationCase.from_mapping(item) for item in raw_cases)
        return cls(_required_string(raw.get("dataset_id"), "dataset_id"), cases)

    @classmethod
    def load(cls, path: str | Path) -> EvaluationDataset:
        dataset_path = Path(path).expanduser()
        try:
            with dataset_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except OSError as error:
            raise EvaluationDatasetError(f"could not read evaluation dataset {dataset_path}") from error
        except json.JSONDecodeError as error:
            raise EvaluationDatasetError(f"evaluation dataset {dataset_path} is not valid JSON") from error
        return cls.from_mapping(raw)

    @property
    def real_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(case for case in self.cases if not case.synthetic)

    @property
    def synthetic_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(case for case in self.cases if case.synthetic)

    @property
    def real_vendor_expiry_cases(self) -> tuple[EvaluationCase, ...]:
        """Return hand-verified vendor-history cases whose ground truth expired."""

        return tuple(
            case
            for case in self.real_cases
            if case.ground_truth_source_type == "vendor_history"
            and case.expected_state == StandingState.EXPIRED
        )

    @property
    def has_real_vendor_expiry(self) -> bool:
        """Whether the corpus contains a non-synthetic vendor-expiry case."""

        return bool(self.real_vendor_expiry_cases)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "cases": [case.as_dict() for case in self.cases],
        }

    def release_case_count(self) -> int:
        """Return only source-linked non-synthetic cases for release accounting."""

        return len(self.real_cases)


@dataclass(frozen=True)
class EvaluationMismatch:
    """One prediction that differs from the case's published ground truth."""

    case_id: str
    expected_state: StandingState
    predicted_state: StandingState

    def as_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "expected_state": self.expected_state.value,
            "predicted_state": self.predicted_state.value,
        }


@dataclass(frozen=True)
class EvaluationMetrics:
    """Deterministic metrics for one complete or partial prediction arm."""

    dataset_id: str
    total_cases: int
    evaluated_cases: int
    correct_cases: int
    missing_case_ids: tuple[str, ...]
    mismatches: tuple[EvaluationMismatch, ...]

    @property
    def accuracy(self) -> float:
        if self.evaluated_cases == 0:
            return 0.0
        return self.correct_cases / self.evaluated_cases

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "total_cases": self.total_cases,
            "evaluated_cases": self.evaluated_cases,
            "correct_cases": self.correct_cases,
            "accuracy": self.accuracy,
            "missing_case_ids": list(self.missing_case_ids),
            "mismatches": [mismatch.as_dict() for mismatch in self.mismatches],
        }


def measure_predictions(
    dataset: EvaluationDataset,
    predictions: Mapping[str, StandingState | str],
) -> EvaluationMetrics:
    """Measure predictions without filling missing cases or trusting extra IDs."""

    case_by_id = {case.case_id: case for case in dataset.cases}
    unknown_ids = sorted(set(predictions) - set(case_by_id))
    if unknown_ids:
        raise EvaluationDatasetError("predictions contain unknown case IDs: " + ", ".join(unknown_ids))

    normalized: dict[str, StandingState] = {}
    for case_id, raw_state in predictions.items():
        if isinstance(raw_state, StandingState):
            normalized[case_id] = raw_state
            continue
        if not isinstance(raw_state, str):
            raise EvaluationDatasetError(f"prediction for {case_id} must be a StandingState")
        try:
            normalized[case_id] = StandingState(raw_state)
        except ValueError as error:
            raise EvaluationDatasetError(f"unknown prediction state {raw_state} for {case_id}") from error

    missing = tuple(sorted(set(case_by_id) - set(normalized)))
    mismatches: list[EvaluationMismatch] = []
    correct = 0
    for case in dataset.cases:
        predicted = normalized.get(case.case_id)
        if predicted is None:
            continue
        if predicted == case.expected_state:
            correct += 1
        else:
            mismatches.append(EvaluationMismatch(case.case_id, case.expected_state, predicted))
    evaluated = len(dataset.cases) - len(missing)
    return EvaluationMetrics(
        dataset.dataset_id,
        len(dataset.cases),
        evaluated,
        correct,
        missing,
        tuple(mismatches),
    )


def sha256_bytes(payload: bytes) -> str:
    """Return the digest format required when pinning a captured source."""

    return hashlib.sha256(payload).hexdigest()


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationDatasetError(f"{label} must be true or false")
    return value
