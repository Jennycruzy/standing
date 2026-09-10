"""Pure acceptance checks and observer selection for one condition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .approval import (
    ApprovalCheck,
    ManualApproval,
    ManualApprovalError,
    check_manual_approval,
    evidence_fingerprint,
)
from .provenance import ObservationProvenance, ProvenanceError, SourceBinding
from .freshness import check_freshness
from .temporal import TemporalEvidence, TemporalObservationError, TemporalResolution, parse_timestamp


class AcceptanceStatus(StrEnum):
    """The two outcomes of the observation acceptance policy."""

    ACCEPTED = "ACCEPTED"
    CONTESTED = "CONTESTED"


class ObserverSelectionError(ValueError):
    """Raised when no observer meets the configured history requirements."""


@dataclass(frozen=True)
class AcceptancePolicy:
    """Runtime policy values loaded from configuration."""

    vendor_primary_source_type: str
    independent_observers: int
    min_observer_history: int
    max_observer_contradictions: int
    manual_approval_required: bool
    require_independence_provenance: bool = False
    max_observation_age_seconds: int | None = None
    recheck_interval_seconds: int | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AcceptancePolicy:
        return cls(
            vendor_primary_source_type=_required_string(raw.get("vendor_primary_source_type"), "vendor_primary_source_type"),
            independent_observers=_positive_int(raw.get("independent_observers"), "independent_observers"),
            min_observer_history=_positive_int(raw.get("min_observer_history"), "min_observer_history"),
            max_observer_contradictions=_nonnegative_int(
                raw.get("max_observer_contradictions"), "max_observer_contradictions"
            ),
            manual_approval_required=_required_bool(
                raw.get("manual_approval_required"), "manual_approval_required"
            ),
            require_independence_provenance=_optional_bool(
                raw.get("require_independence_provenance", False),
                "require_independence_provenance",
            ),
            max_observation_age_seconds=_optional_positive_int(
                raw.get("max_observation_age_seconds"),
                "max_observation_age_seconds",
            ),
            recheck_interval_seconds=_optional_positive_int(
                raw.get("recheck_interval_seconds"),
                "recheck_interval_seconds",
            ),
        )


def load_acceptance_policy(path: str | Path) -> AcceptancePolicy:
    """Load the acceptance policy from the project's JSON configuration."""

    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("acceptance policy file must contain an object")
    section = raw.get("acceptance")
    if not isinstance(section, dict):
        raise ValueError("acceptance policy file must contain an acceptance object")
    return AcceptancePolicy.from_mapping(section)


@dataclass(frozen=True)
class ObserverHistory:
    """Reliability counters and identity metadata kept for one observer.

    The entity key remains the observer's stable address.  The additional
    fields make the dimensions used by the acceptance policy inspectable in
    memory instead of forcing consumers to infer them from counters or wallet
    addresses.  They are optional for backwards compatibility with the first
    ledger format, but are preserved whenever present.
    """

    address: str
    readings_given: int
    readings_confirmed: int
    readings_contradicted: int
    wallet_address: str | None = None
    operator_id: str | None = None
    operator_type: str | None = None
    source_domains: tuple[str, ...] = ()
    extraction_methods: tuple[str, ...] = ()
    extraction_versions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.address.strip():
            raise ValueError("observer address must not be empty")
        for name, identity_value in (
            ("wallet_address", self.wallet_address),
            ("operator_id", self.operator_id),
            ("operator_type", self.operator_type),
        ):
            if identity_value is not None and (not isinstance(identity_value, str) or not identity_value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")
        if self.wallet_address is not None and self.wallet_address.strip() != self.address.strip():
            raise ValueError("wallet_address must match the observer address")
        for name, metadata_values in (
            ("source_domains", self.source_domains),
            ("extraction_methods", self.extraction_methods),
            ("extraction_versions", self.extraction_versions),
        ):
            if not isinstance(metadata_values, tuple):
                raise ValueError(f"{name} must be a tuple of strings")
            if any(not isinstance(item, str) or not item.strip() for item in metadata_values):
                raise ValueError(f"{name} must contain only non-empty strings")
        for name, count in (
            ("readings_given", self.readings_given),
            ("readings_confirmed", self.readings_confirmed),
            ("readings_contradicted", self.readings_contradicted),
        ):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.readings_given < self.readings_confirmed + self.readings_contradicted:
            raise ValueError("observer readings_given is smaller than its outcomes")

    @classmethod
    def from_mapping(cls, address: str, raw: Mapping[str, Any]) -> ObserverHistory:
        confirmed = _count(raw.get("readings_confirmed", 0), "readings_confirmed")
        contradicted = _count(raw.get("readings_contradicted", 0), "readings_contradicted")
        given_raw = raw.get("readings_given")
        given = confirmed + contradicted if given_raw is None else _count(given_raw, "readings_given")
        return cls(
            address,
            given,
            confirmed,
            contradicted,
            _optional_identity(raw.get("wallet_address", address), "wallet_address"),
            _optional_identity(raw.get("operator_id"), "operator_id"),
            _optional_identity(raw.get("operator_type"), "operator_type"),
            _identity_values(raw.get("source_domains", ()), "source_domains"),
            _identity_values(raw.get("extraction_methods", ()), "extraction_methods"),
            _identity_values(raw.get("extraction_versions", ()), "extraction_versions"),
        )

    def meets(self, policy: AcceptancePolicy) -> bool:
        return (
            self.readings_confirmed >= policy.min_observer_history
            and self.readings_contradicted <= policy.max_observer_contradictions
        )

    def as_counts(self) -> dict[str, int]:
        return {
            "readings_given": self.readings_given,
            "readings_confirmed": self.readings_confirmed,
            "readings_contradicted": self.readings_contradicted,
        }

    def as_dict(self) -> dict[str, Any]:
        """Return counters and observer identity metadata for Sibyl."""

        return {
            **self.as_counts(),
            "wallet_address": self.wallet_address or self.address,
            "operator_id": self.operator_id,
            "operator_type": self.operator_type,
            "source_domains": list(self.source_domains),
            "extraction_methods": list(self.extraction_methods),
            "extraction_versions": list(self.extraction_versions),
        }


def select_observer(
    histories: Sequence[ObserverHistory],
    policy: AcceptancePolicy,
) -> ObserverHistory:
    """Choose the strongest eligible observer deterministically."""

    eligible = [history for history in histories if history.meets(policy)]
    if not eligible:
        raise ObserverSelectionError("no observer meets the configured history requirements")
    return min(
        eligible,
        key=lambda history: (
            history.readings_contradicted,
            -history.readings_confirmed,
            -history.readings_given,
            history.address,
        ),
    )


def apply_observer_outcome(history: ObserverHistory, *, confirmed: bool) -> ObserverHistory:
    """Return the next reliability record after one checked reading."""

    return ObserverHistory(
        address=history.address,
        readings_given=history.readings_given + 1,
        readings_confirmed=history.readings_confirmed + (1 if confirmed else 0),
        readings_contradicted=history.readings_contradicted + (0 if confirmed else 1),
        wallet_address=history.wallet_address,
        operator_id=history.operator_id,
        operator_type=history.operator_type,
        source_domains=history.source_domains,
        extraction_methods=history.extraction_methods,
        extraction_versions=history.extraction_versions,
    )


@dataclass(frozen=True)
class AcceptanceResult:
    """The pure policy result for a condition's observations."""

    condition_key: str
    status: AcceptanceStatus
    accepted_value: Any
    vendor_primary_present: bool
    independent_observer_addresses: tuple[str, ...]
    manual_approval: bool
    observation_uids: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_fingerprint: str = ""
    manual_approval_id: str | None = None
    manual_approval_valid: bool = False
    independent_operator_ids: tuple[str, ...] = ()
    independent_source_ids: tuple[str, ...] = ()
    independent_extractor_ids: tuple[str, ...] = ()
    freshness_checked: bool = False
    stale_observation_uids: tuple[str, ...] = ()
    canonical_observation_uids: tuple[str, ...] = ()
    temporal_conflict: bool = False

    @property
    def accepted(self) -> bool:
        return self.status == AcceptanceStatus.ACCEPTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "status": self.status.value,
            "accepted": self.accepted,
            "accepted_value": _stable_value(self.accepted_value),
            "vendor_primary_present": self.vendor_primary_present,
            "independent_observer_addresses": list(self.independent_observer_addresses),
            "manual_approval": self.manual_approval,
            "observation_uids": list(self.observation_uids),
            "reasons": list(self.reasons),
            "evidence_fingerprint": self.evidence_fingerprint,
            "manual_approval_id": self.manual_approval_id,
            "manual_approval_valid": self.manual_approval_valid,
            "independent_operator_ids": list(self.independent_operator_ids),
            "independent_source_ids": list(self.independent_source_ids),
            "independent_extractor_ids": list(self.independent_extractor_ids),
            "freshness_checked": self.freshness_checked,
            "stale_observation_uids": list(self.stale_observation_uids),
            "canonical_observation_uids": list(self.canonical_observation_uids),
            "temporal_conflict": self.temporal_conflict,
        }


@dataclass(frozen=True)
class _Observation:
    value: Any
    value_type: str | None
    unit: str | None
    source_type: str
    observer_address: str | None
    observation_uid: str
    source_url: str | None
    publisher_id: str | None
    provenance: ObservationProvenance | None
    effective_from: int | None
    observed_at: int | None
    recorded_at: int | None


def check_acceptance(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    observer_records: Mapping[str, Mapping[str, Any]],
    *,
    manual_approval: bool,
    manual_approval_record: Mapping[str, Any] | None = None,
    policy: AcceptancePolicy,
    source_binding: Mapping[str, Any] | None = None,
    now_unix: int | None = None,
) -> AcceptanceResult:
    """Apply the configured policy without I/O or a model call."""

    key = _required_string(condition_key, "condition_key")
    if not isinstance(manual_approval, bool):
        raise ValueError("manual_approval must be true or false")
    try:
        evidence_digest = evidence_fingerprint(key, observations)
    except ManualApprovalError as error:
        raise ValueError(str(error)) from error
    approval_check = ApprovalCheck(False, None, "No explicit human approval record is present.")
    if manual_approval_record is not None:
        try:
            approval = ManualApproval.from_mapping(manual_approval_record)
            approval_check = check_manual_approval(
                approval,
                condition_key=key,
                evidence_digest=evidence_digest,
            )
        except ManualApprovalError as error:
            approval_check = ApprovalCheck(False, None, str(error))
    normalized = tuple(_observation(key, raw) for raw in observations)
    reasons: list[str] = []
    temporal_resolution: TemporalResolution | None = None
    try:
        temporal_resolution = _resolve_temporal(key, observations, now_unix=now_unix)
    except ValueError as error:
        # A malformed/incomplete temporal row is an evidence failure, not a
        # reason to raise a caller out of the conservative acceptance path.
        reasons.append(str(error))
    binding = SourceBinding.from_mapping(source_binding) if source_binding is not None else None
    freshness_checked = (
        (policy.max_observation_age_seconds is not None or policy.recheck_interval_seconds is not None)
        and now_unix is not None
    )
    stale_observation_uids: tuple[str, ...] = ()
    if freshness_checked:
        freshness_observations = normalized
        if temporal_resolution is not None:
            current_uids = {item.observation_uid for item in temporal_resolution.candidates}
            freshness_observations = tuple(
                item for item in normalized if item.observation_uid in current_uids
            )
        freshness = check_freshness(
            [
                {
                    "observation_uid": item.observation_uid,
                    "effective_from": item.effective_from,
                    "observed_at": item.observed_at,
                    "recorded_at": item.recorded_at,
                }
                for item in freshness_observations
            ],
            now_unix=now_unix if now_unix is not None else 0,
            max_age_seconds=policy.max_observation_age_seconds
            if policy.max_observation_age_seconds is not None
            else policy.recheck_interval_seconds
            if policy.recheck_interval_seconds is not None
            else 1,
            recheck_interval_seconds=policy.recheck_interval_seconds,
        )
        reasons.extend(freshness.reasons)
        stale_observation_uids = tuple(
            sorted(
                set(freshness.stale_observation_uids)
                | set(freshness.missing_timestamp_uids)
                | set(freshness.future_timestamp_uids)
                | set(freshness.scheduled_recheck_uids)
            )
        )
    vendor_primary = tuple(
        item for item in normalized if item.source_type == policy.vendor_primary_source_type
    )
    trusted_vendor_primary = tuple(
        item
        for item in vendor_primary
        if _trusted_vendor_observation(item, binding, reasons)
    )
    if binding is not None:
        for item in normalized:
            if item.source_url is None or not binding.allows(item.source_url):
                reasons.append(
                    f"Observation {item.observation_uid} is outside the trusted source boundary."
                )
            if binding.value_type is not None and item.value_type != binding.value_type:
                reasons.append(
                    f"Observation {item.observation_uid} has the wrong value type for the condition."
                )
            if binding.unit is not None and item.unit != binding.unit:
                reasons.append(
                    f"Observation {item.observation_uid} has the wrong unit for the condition."
                )
    independent_addresses = tuple(
        sorted(
            {
                item.observer_address
                for item in normalized
                if item.source_type != policy.vendor_primary_source_type
                and item.observer_address is not None
            }
        )
    )

    provenance_by_address: dict[str, set[ObservationProvenance]] = {}
    for item in normalized:
        if item.source_type == policy.vendor_primary_source_type:
            continue
        address = item.observer_address
        if address is None or item.provenance is None:
            continue
        provenance_by_address.setdefault(address, set()).add(item.provenance)

    complete_provenance = [
        address
        for address in independent_addresses
        if len(provenance_by_address.get(address, set())) == 1
    ]
    independent_provenance = tuple(
        sorted(
            provenance_by_address[address],
            key=lambda item: (item.operator_id, item.source_id, item.extractor_id),
        )[0]
        for address in complete_provenance
    )
    operator_ids = tuple(sorted({item.operator_id for item in independent_provenance}))
    source_ids = tuple(sorted({item.source_id for item in independent_provenance}))
    extractor_ids = tuple(sorted({item.extractor_id for item in independent_provenance}))

    if not trusted_vendor_primary:
        reasons.append("No vendor-published observation is present.")
    if len(independent_addresses) < policy.independent_observers:
        reasons.append(
            f"Only {len(independent_addresses)} independent observer(s) are present; "
            f"the policy requires {policy.independent_observers}."
        )
    if policy.require_independence_provenance:
        missing = [
            address
            for address in independent_addresses
            if len(provenance_by_address.get(address, set())) == 0
        ]
        if missing:
            reasons.append(
                "Independent observers are missing operator, source, or extractor provenance: "
                + ", ".join(missing)
                + "."
            )
        inconsistent = [
            address
            for address in independent_addresses
            if len(provenance_by_address.get(address, set())) > 1
        ]
        if inconsistent:
            reasons.append(
                "An observer changed provenance across readings: "
                + ", ".join(inconsistent)
                + "."
            )
        if len(operator_ids) != len(complete_provenance):
            reasons.append("Independent observers share an operator identity.")
        if len(source_ids) != len(complete_provenance):
            reasons.append("Independent observers share a source identity.")
        if len(extractor_ids) != len(complete_provenance):
            reasons.append("Independent observers share an extractor identity.")
    if policy.manual_approval_required and not manual_approval:
        reasons.append("A human approval is required before this value can be accepted.")
    if policy.manual_approval_required and manual_approval_record is None:
        reasons.append("The manual-approval flag must include a persisted human approval record.")
    if policy.manual_approval_required and manual_approval_record is not None and not approval_check.valid:
        reasons.append(approval_check.reason)

    for address in independent_addresses:
        record = observer_records.get(address)
        if record is None:
            reasons.append(f"No reliability record is available for observer {address}.")
            continue
        history = ObserverHistory.from_mapping(address, record)
        if not history.meets(policy):
            reasons.append(
                f"Observer {address} does not meet the required history: "
                f"{history.readings_confirmed} confirmed reading(s) and "
                f"{history.readings_contradicted} contradicted reading(s)."
            )

    accepted_value: Any = None
    canonical_observation_uids: tuple[str, ...] = ()
    temporal_conflict = False
    if temporal_resolution is not None:
        canonical_observation_uids = tuple(
            item.observation_uid for item in temporal_resolution.candidates
        )
        temporal_conflict = temporal_resolution.conflict
        if temporal_resolution.conflict:
            reasons.append("Incompatible observations share the same effective period.")
        elif temporal_resolution.current is None:
            reasons.append("No observation covers the current valid-time point.")
        else:
            accepted_value = temporal_resolution.current.value
    else:
        distinct_values = {_canonical_json(item.value) for item in normalized}
        if len(distinct_values) > 1:
            reasons.append("The available observations disagree about the current value.")
        if normalized:
            accepted_value = normalized[0].value
    if not normalized:
        reasons.append("No observation is available for this condition.")

    accepted = not reasons
    return AcceptanceResult(
        condition_key=key,
        status=AcceptanceStatus.ACCEPTED if accepted else AcceptanceStatus.CONTESTED,
        accepted_value=accepted_value if accepted else None,
        vendor_primary_present=bool(trusted_vendor_primary),
        independent_observer_addresses=independent_addresses,
        manual_approval=manual_approval,
        observation_uids=tuple(sorted(item.observation_uid for item in normalized)),
        reasons=tuple(reasons),
        evidence_fingerprint=evidence_digest,
        manual_approval_id=approval_check.approval_id,
        manual_approval_valid=approval_check.valid,
        independent_operator_ids=operator_ids,
        independent_source_ids=source_ids,
        independent_extractor_ids=extractor_ids,
        freshness_checked=freshness_checked,
        stale_observation_uids=stale_observation_uids,
        canonical_observation_uids=canonical_observation_uids,
        temporal_conflict=temporal_conflict,
    )


def _observation(condition_key: str, raw: Mapping[str, Any]) -> _Observation:
    raw_key = raw.get("condition_key")
    if raw_key is not None and raw_key != condition_key:
        raise ValueError("observation condition_key does not match the requested condition")
    value = raw.get("value")
    if value is None:
        raise ValueError("observation value must be present")
    source_type = _required_string(raw.get("source_type"), "observation source_type")
    raw_value_type = raw.get("value_type")
    value_type = None
    if raw_value_type is not None:
        value_type = _required_string(raw_value_type, "observation value_type")
    raw_unit = raw.get("unit")
    unit = None
    if raw_unit is not None:
        unit = _required_string(raw_unit, "observation unit").lower()
    uid = _required_string(raw.get("observation_uid"), "observation_uid")
    raw_address = raw.get("observer_address")
    if raw_address is not None and (not isinstance(raw_address, str) or not raw_address.strip()):
        raise ValueError("observer_address must be a non-empty string when supplied")
    observer_address = raw_address.strip() if isinstance(raw_address, str) else None
    raw_source_url = raw.get("source_url")
    source_url = None
    if raw_source_url is not None:
        if not isinstance(raw_source_url, str) or not raw_source_url.strip():
            raise ValueError("source_url must be a non-empty string when supplied")
        source_url = raw_source_url.strip()
    raw_publisher = raw.get("publisher_id")
    publisher_id = None
    if raw_publisher is not None:
        if not isinstance(raw_publisher, str) or not raw_publisher.strip():
            raise ValueError("publisher_id must be a non-empty string when supplied")
        publisher_id = raw_publisher.strip()
    raw_provenance = raw.get("provenance")
    provenance = None
    if raw_provenance is not None:
        try:
            provenance = ObservationProvenance.from_mapping(raw_provenance)
        except ProvenanceError as error:
            raise ValueError(str(error)) from error
    raw_effective_from = raw.get("effective_from")
    effective_from = None
    if raw_effective_from is not None:
        try:
            effective_from = parse_timestamp(raw_effective_from, label="effective_from")
        except TemporalObservationError as error:
            raise ValueError("effective_from must be a non-negative integer or ISO date when supplied") from error
    raw_observed_at = raw.get("observed_at")
    observed_at = None if raw_observed_at is None else parse_timestamp(raw_observed_at, label="observed_at")
    raw_recorded_at = raw.get("recorded_at")
    recorded_at = None if raw_recorded_at is None else parse_timestamp(raw_recorded_at, label="recorded_at")
    if observed_at is not None and recorded_at is not None and recorded_at < observed_at:
        raise ValueError("recorded_at must not precede observed_at")
    return _Observation(
        value,
        value_type,
        unit,
        source_type,
        observer_address,
        uid,
        source_url,
        publisher_id,
        provenance,
        effective_from,
        observed_at,
        recorded_at,
    )


def _resolve_temporal(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    now_unix: int | None,
) -> TemporalResolution | None:
    """Resolve a complete temporal set while keeping legacy rows explicit.

    A completely legacy set is still readable for compatibility with the old
    live ledger. Once any row claims temporal metadata, however, silently
    falling back to the pre-temporal "first value wins" behavior would turn a
    malformed record into accepted evidence. New temporal rows therefore have
    to be complete as a set and pass the strict evidence contract.
    """

    has_temporal_fields = any(_has_temporal_fields(item) for item in observations)
    if not has_temporal_fields:
        return None
    try:
        # Any record that enters the temporal branch is a new governed
        # observation, so use the strict parser. This validates types, units,
        # source identity, hashes, and all three relevant timestamps together.
        evidence = TemporalEvidence.from_mappings(
            observations,
            strict=True,
            condition_key=condition_key,
        )
    except TemporalObservationError as error:
        raise ValueError(f"temporal observation set is invalid: {error}") from error
    # Acceptance must inspect candidate evidence before it can mark the
    # winning rows accepted. Product-facing temporal queries default to
    # accepted-only; this explicit opt-out is the policy's pre-promotion view.
    return evidence.resolve(valid_at=now_unix, accepted_only=False)


def _has_temporal_fields(observation: Mapping[str, Any]) -> bool:
    return any(
        observation.get(field) is not None
        for field in ("effective_from", "effective_until", "observed_at", "recorded_at")
    )


def _trusted_vendor_observation(
    observation: _Observation,
    binding: SourceBinding | None,
    reasons: list[str],
) -> bool:
    if binding is None:
        return True
    if observation.source_url is None or not binding.allows(observation.source_url, require_canonical=True):
        reasons.append(
            f"Vendor observation {observation.observation_uid} is not from the canonical trusted source."
        )
        return False
    if binding.publisher_id is not None and observation.publisher_id != binding.publisher_id:
        reasons.append(
            f"Vendor observation {observation.observation_uid} is not attributed to the trusted publisher."
        )
        return False
    if binding.source_type is not None and observation.source_type != binding.source_type:
        reasons.append(
            f"Vendor observation {observation.observation_uid} has an untrusted source type."
        )
        return False
    if binding.value_type is not None and observation.value_type != binding.value_type:
        reasons.append(
            f"Vendor observation {observation.observation_uid} has the wrong value type."
        )
        return False
    if binding.unit is not None and observation.unit != binding.unit:
        reasons.append(
            f"Vendor observation {observation.observation_uid} has the wrong unit."
        )
        return False
    return True


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


def _optional_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer when supplied")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result < 1:
        raise ValueError(f"{label} must be at least 1")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _count(value: Any, label: str) -> int:
    return _nonnegative_int(value, label)


def _optional_identity(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def _identity_values(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a list of strings")
    normalized = {
        _required_string(item, f"{label} item")
        for item in value
    }
    return tuple(sorted(normalized))


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        pairs = ((str(key), _stable_value(item)) for key, item in value.items())
        return {key: item for key, item in sorted(pairs)}
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        values = [_stable_value(item) for item in value]
        return sorted(values, key=_canonical_json)
    raise TypeError(f"value of type {type(value).__name__} cannot be compared")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _stable_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
