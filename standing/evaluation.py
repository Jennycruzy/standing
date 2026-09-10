"""Source-linked evaluation datasets and deterministic measurement."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .evaluator import StandingState


_BLOCKING_STATES = frozenset(
    {StandingState.EXPIRED, StandingState.UNKNOWN, StandingState.CONTESTED}
)


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


def _optional_https_url(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _https_url(value, label)


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, label)


def _optional_hash(value: Any, label: str) -> str | None:
    if value is None:
        return None
    digest = _required_string(value, label)
    if not _HEX_DIGEST.fullmatch(digest):
        raise EvaluationDatasetError(f"{label} must be a 64-character SHA-256 digest")
    return digest


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
    historical_ground_truth_url: str | None = None
    historical_ground_truth_effective_at: int | None = None
    historical_source_sha256: str | None = None
    current_ground_truth_url: str | None = None
    current_ground_truth_effective_at: int | None = None
    current_source_sha256: str | None = None
    decision_snapshot_sha256: str | None = None
    condition_key: str | None = None
    predicate: str | None = None
    governed_paths: tuple[str, ...] = ()
    historical_claim: str | None = None
    current_claim: str | None = None
    human_reviewed: bool = False
    reviewed_at: int | None = None
    reviewed_by: str | None = None

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
        optional_urls = (
            (self.historical_ground_truth_url, "historical_ground_truth_url"),
            (self.current_ground_truth_url, "current_ground_truth_url"),
        )
        for url, label in optional_urls:
            if url is not None:
                _https_url(url, label)
        optional_times = (
            (self.historical_ground_truth_effective_at, "historical_ground_truth_effective_at"),
            (self.current_ground_truth_effective_at, "current_ground_truth_effective_at"),
        )
        for timestamp, label in optional_times:
            if timestamp is not None:
                _nonnegative_int(timestamp, label)
        optional_hashes = (
            (self.historical_source_sha256, "historical_source_sha256"),
            (self.current_source_sha256, "current_source_sha256"),
            (self.decision_snapshot_sha256, "decision_snapshot_sha256"),
        )
        for digest, label in optional_hashes:
            if digest is not None and not _HEX_DIGEST.fullmatch(digest):
                raise EvaluationDatasetError(f"{label} must be a 64-character SHA-256 digest")
        optional_claims = (
            (self.condition_key, "condition_key"),
            (self.predicate, "predicate"),
            (self.historical_claim, "historical_claim"),
            (self.current_claim, "current_claim"),
        )
        for claim, label in optional_claims:
            if claim is not None:
                _required_string(claim, label)
        if not isinstance(self.governed_paths, tuple):
            raise EvaluationDatasetError("governed_paths must be a tuple")
        for path in self.governed_paths:
            _required_string(path, "governed_paths entry")
        if not isinstance(self.human_reviewed, bool):
            raise EvaluationDatasetError("human_reviewed must be true or false")
        if self.reviewed_at is not None:
            _nonnegative_int(self.reviewed_at, "reviewed_at")
        if self.reviewed_by is not None:
            _required_string(self.reviewed_by, "reviewed_by")
        if not self.synthetic:
            required_chain = (
                (self.historical_ground_truth_url, "historical_ground_truth_url"),
                (self.historical_ground_truth_effective_at, "historical_ground_truth_effective_at"),
                (self.historical_source_sha256, "historical_source_sha256"),
                (self.current_ground_truth_url, "current_ground_truth_url"),
                (self.current_ground_truth_effective_at, "current_ground_truth_effective_at"),
                (self.current_source_sha256, "current_source_sha256"),
                (self.decision_snapshot_sha256, "decision_snapshot_sha256"),
                (self.condition_key, "condition_key"),
                (self.predicate, "predicate"),
                (self.historical_claim, "historical_claim"),
                (self.current_claim, "current_claim"),
            )
            missing = [label for value, label in required_chain if value is None]
            if missing:
                raise EvaluationDatasetError(
                    "non-synthetic cases require a historical/current evidence chain: "
                    + ", ".join(missing)
                )
            if not self.governed_paths:
                raise EvaluationDatasetError(
                    "non-synthetic cases require at least one governed path"
                )
            if self.human_reviewed and (self.reviewed_at is None or self.reviewed_by is None):
                raise EvaluationDatasetError(
                    "human-reviewed cases require reviewed_at and reviewed_by"
                )

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
        raw_paths = raw.get("governed_paths", ())
        if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, (str, bytes)):
            raise EvaluationDatasetError("governed_paths must be a list")
        paths = tuple(_required_string(path, "governed_paths entry") for path in raw_paths)
        return cls(
            case_id=_required_string(raw.get("case_id"), "case_id"),
            repository=_required_string(raw.get("repository"), "repository"),
            decision_url=_https_url(raw.get("decision_url"), "decision_url"),
            decision_ref=_required_string(raw.get("decision_ref"), "decision_ref"),
            ground_truth_url=_https_url(raw.get("ground_truth_url"), "ground_truth_url"),
            ground_truth_source_type=source_type,
            ground_truth_effective_at=_nonnegative_int(raw.get("ground_truth_effective_at"), "ground_truth_effective_at"),
            captured_at=_nonnegative_int(raw.get("captured_at"), "captured_at"),
            source_sha256=_required_string(raw.get("source_sha256"), "source_sha256"),
            expected_state=state,
            synthetic=_required_bool(raw.get("synthetic"), "synthetic"),
            notes=raw.get("notes") if raw.get("notes") is None else _required_string(raw.get("notes"), "notes"),
            historical_ground_truth_url=_optional_https_url(raw.get("historical_ground_truth_url"), "historical_ground_truth_url"),
            historical_ground_truth_effective_at=_optional_nonnegative_int(
                raw.get("historical_ground_truth_effective_at"),
                "historical_ground_truth_effective_at",
            ),
            historical_source_sha256=_optional_hash(raw.get("historical_source_sha256"), "historical_source_sha256"),
            current_ground_truth_url=_optional_https_url(raw.get("current_ground_truth_url"), "current_ground_truth_url"),
            current_ground_truth_effective_at=_optional_nonnegative_int(
                raw.get("current_ground_truth_effective_at"),
                "current_ground_truth_effective_at",
            ),
            current_source_sha256=_optional_hash(raw.get("current_source_sha256"), "current_source_sha256"),
            decision_snapshot_sha256=_optional_hash(raw.get("decision_snapshot_sha256"), "decision_snapshot_sha256"),
            condition_key=_optional_string(raw.get("condition_key"), "condition_key"),
            predicate=_optional_string(raw.get("predicate"), "predicate"),
            governed_paths=paths,
            historical_claim=_optional_string(raw.get("historical_claim"), "historical_claim"),
            current_claim=_optional_string(raw.get("current_claim"), "current_claim"),
            human_reviewed=_required_bool(raw.get("human_reviewed", False), "human_reviewed"),
            reviewed_at=_optional_nonnegative_int(raw.get("reviewed_at"), "reviewed_at"),
            reviewed_by=_optional_string(raw.get("reviewed_by"), "reviewed_by"),
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
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
            "governed_paths": list(self.governed_paths),
            "human_reviewed": self.human_reviewed,
        }
        optional_fields = {
            "historical_ground_truth_url": self.historical_ground_truth_url,
            "historical_ground_truth_effective_at": self.historical_ground_truth_effective_at,
            "historical_source_sha256": self.historical_source_sha256,
            "current_ground_truth_url": self.current_ground_truth_url,
            "current_ground_truth_effective_at": self.current_ground_truth_effective_at,
            "current_source_sha256": self.current_source_sha256,
            "decision_snapshot_sha256": self.decision_snapshot_sha256,
            "condition_key": self.condition_key,
            "predicate": self.predicate,
            "historical_claim": self.historical_claim,
            "current_claim": self.current_claim,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
        }
        result.update({key: value for key, value in optional_fields.items() if value is not None})
        return result


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
    def reviewed_real_cases(self) -> tuple[EvaluationCase, ...]:
        """Return real cases with an explicit human review marker."""

        return tuple(case for case in self.real_cases if case.human_reviewed)

    @property
    def pending_real_cases(self) -> tuple[EvaluationCase, ...]:
        """Return source-linked real candidates awaiting human review."""

        return tuple(case for case in self.real_cases if not case.human_reviewed)

    @property
    def synthetic_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(case for case in self.cases if case.synthetic)

    @property
    def real_vendor_expiry_cases(self) -> tuple[EvaluationCase, ...]:
        """Return hand-verified vendor-history cases whose ground truth expired."""

        return tuple(
            case
            for case in self.reviewed_real_cases
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

        return len(self.reviewed_real_cases)


@dataclass(frozen=True)
class EvaluationMismatch:
    """One prediction that differs from the case's published ground truth."""

    case_id: str
    expected_state: StandingState
    predicted_state: StandingState
    why: str | None = None
    fixed: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "case_id": self.case_id,
            "expected_state": self.expected_state.value,
            "predicted_state": self.predicted_state.value,
        }
        if self.why is not None:
            result["why"] = self.why
        if self.fixed is not None:
            result["fixed"] = self.fixed
        return result


@dataclass(frozen=True)
class EvaluationMetrics:
    """Deterministic metrics for one complete or partial prediction arm."""

    dataset_id: str
    total_cases: int
    evaluated_cases: int
    correct_cases: int
    missing_case_ids: tuple[str, ...]
    mismatches: tuple[EvaluationMismatch, ...]
    expected_state_counts: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)
    predicted_state_counts: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)
    correct_state_counts: Mapping[str, int] = field(default_factory=dict, repr=False, compare=False)

    @property
    def accuracy(self) -> float:
        if self.evaluated_cases == 0:
            return 0.0
        return self.correct_cases / self.evaluated_cases

    @property
    def expired_decision_precision(self) -> float:
        """Precision of predictions that identify an expired decision."""

        predicted_expired = self._predicted_expired_cases
        if predicted_expired == 0:
            return 0.0
        return self._true_expired_cases / predicted_expired

    @property
    def expired_decision_recall(self) -> float:
        """Recall of the expired cases represented in this metric."""

        expected_expired = self._expected_expired_cases
        if expected_expired == 0:
            return 0.0
        return self._true_expired_cases / expected_expired

    @property
    def false_block_rate(self) -> float:
        """Rate of standing cases incorrectly assigned a blocking state."""

        expected_stands = self._expected_stands_cases
        if expected_stands == 0:
            return 0.0
        return self._false_block_cases / expected_stands

    @property
    def missed_expiry_rate(self) -> float:
        """Rate of expected expiries that were not predicted as EXPIRED."""

        expected_expired = self._expected_expired_cases
        if expected_expired == 0:
            return 0.0
        return (expected_expired - self._true_expired_cases) / expected_expired

    @property
    def unknown_rate(self) -> float:
        """Share of evaluated predictions that returned UNKNOWN."""

        if self.evaluated_cases == 0:
            return 0.0
        return self._predicted_state_count(StandingState.UNKNOWN) / self.evaluated_cases

    @property
    def contested_rate(self) -> float:
        """Share of evaluated predictions that returned CONTESTED."""

        if self.evaluated_cases == 0:
            return 0.0
        return self._predicted_state_count(StandingState.CONTESTED) / self.evaluated_cases

    @property
    def _expected_expired_cases(self) -> int:
        return self._count_expected(StandingState.EXPIRED)

    @property
    def _expected_stands_cases(self) -> int:
        return self._count_expected(StandingState.STANDS)

    @property
    def _predicted_expired_cases(self) -> int:
        return self._count_predicted(StandingState.EXPIRED)

    @property
    def _true_expired_cases(self) -> int:
        return sum(
            1
            for mismatch in self.mismatches
            if mismatch.expected_state == StandingState.EXPIRED
            and mismatch.predicted_state == StandingState.EXPIRED
        ) + self._correct_state_count(StandingState.EXPIRED)

    @property
    def _false_block_cases(self) -> int:
        return sum(
            1
            for mismatch in self.mismatches
            if mismatch.expected_state == StandingState.STANDS
            and mismatch.predicted_state in _BLOCKING_STATES
        )

    def _count_expected(self, state: StandingState) -> int:
        return int(self.expected_state_counts.get(state.value, 0))

    def _count_predicted(self, state: StandingState) -> int:
        return int(self.predicted_state_counts.get(state.value, 0))

    def _correct_state_count(self, state: StandingState) -> int:
        return int(self.correct_state_counts.get(state.value, 0))

    def _predicted_state_count(self, state: StandingState) -> int:
        return self._count_predicted(state)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "total_cases": self.total_cases,
            "evaluated_cases": self.evaluated_cases,
            "correct_cases": self.correct_cases,
            "accuracy": self.accuracy,
            "expired_decision_precision": self.expired_decision_precision,
            "expired_decision_recall": self.expired_decision_recall,
            "false_block_rate": self.false_block_rate,
            "missed_expiry_rate": self.missed_expiry_rate,
            "unknown_rate": self.unknown_rate,
            "contested_rate": self.contested_rate,
            "missing_case_ids": list(self.missing_case_ids),
            "mismatches": [mismatch.as_dict() for mismatch in self.mismatches],
        }


def measure_predictions(
    dataset: EvaluationDataset,
    predictions: Mapping[str, StandingState | str | Mapping[str, Any]],
) -> EvaluationMetrics:
    """Measure predictions without filling missing cases or trusting extra IDs.

    A prediction may be a state string or an object with ``state`` plus the
    optional miss-audit fields ``why`` and ``fixed``.  The latter are carried
    into published mismatch records so an evaluation report can explain each
    error instead of hiding it behind one aggregate number.
    """

    case_by_id = {case.case_id: case for case in dataset.cases}
    unknown_ids = sorted(set(predictions) - set(case_by_id))
    if unknown_ids:
        raise EvaluationDatasetError("predictions contain unknown case IDs: " + ", ".join(unknown_ids))

    normalized: dict[str, StandingState] = {}
    audit: dict[str, tuple[str | None, bool | None]] = {}
    for case_id, raw_state in predictions.items():
        if isinstance(raw_state, StandingState):
            normalized[case_id] = raw_state
            continue
        raw_value: Any = raw_state
        if isinstance(raw_state, Mapping):
            allowed = {"state", "why", "fixed"}
            extra = sorted(str(key) for key in raw_state if str(key) not in allowed)
            if extra:
                raise EvaluationDatasetError(
                    f"prediction audit for {case_id} contains unsupported fields: {', '.join(extra)}"
                )
            raw_value = raw_state.get("state")
            why_raw = raw_state.get("why")
            fixed_raw = raw_state.get("fixed")
            why = None if why_raw is None else _required_string(why_raw, f"prediction why for {case_id}")
            fixed = None if fixed_raw is None else _required_bool(fixed_raw, f"prediction fixed for {case_id}")
            audit[case_id] = (why, fixed)
        if not isinstance(raw_value, str):
            raise EvaluationDatasetError(f"prediction for {case_id} must be a StandingState or object")
        try:
            normalized[case_id] = StandingState(raw_value)
        except ValueError as error:
            raise EvaluationDatasetError(f"unknown prediction state {raw_value} for {case_id}") from error

    missing = tuple(sorted(set(case_by_id) - set(normalized)))
    mismatches: list[EvaluationMismatch] = []
    correct = 0
    expected_state_counts: dict[str, int] = {}
    predicted_state_counts: dict[str, int] = {}
    correct_state_counts: dict[str, int] = {}
    for case in dataset.cases:
        predicted = normalized.get(case.case_id)
        if predicted is None:
            continue
        expected_state_counts[case.expected_state.value] = expected_state_counts.get(case.expected_state.value, 0) + 1
        predicted_state_counts[predicted.value] = predicted_state_counts.get(predicted.value, 0) + 1
        if predicted == case.expected_state:
            correct += 1
            correct_state_counts[predicted.value] = correct_state_counts.get(predicted.value, 0) + 1
        else:
            why, fixed = audit.get(case.case_id, (None, None))
            mismatches.append(
                EvaluationMismatch(case.case_id, case.expected_state, predicted, why=why, fixed=fixed)
            )
    evaluated = len(dataset.cases) - len(missing)
    return EvaluationMetrics(
        dataset.dataset_id,
        len(dataset.cases),
        evaluated,
        correct,
        missing,
        tuple(mismatches),
        expected_state_counts,
        predicted_state_counts,
        correct_state_counts,
    )


def sha256_bytes(payload: bytes) -> str:
    """Return the digest format required when pinning a captured source."""

    return hashlib.sha256(payload).hexdigest()


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationDatasetError(f"{label} must be true or false")
    return value
