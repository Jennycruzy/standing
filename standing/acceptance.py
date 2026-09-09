"""Pure acceptance checks and observer selection for one condition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .provenance import ObservationProvenance, ProvenanceError, SourceBinding
from .freshness import check_freshness


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
    """The reliability counts kept for one observer."""

    address: str
    readings_given: int
    readings_confirmed: int
    readings_contradicted: int

    def __post_init__(self) -> None:
        if not self.address.strip():
            raise ValueError("observer address must not be empty")
        for name, value in (
            ("readings_given", self.readings_given),
            ("readings_confirmed", self.readings_confirmed),
            ("readings_contradicted", self.readings_contradicted),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.readings_given < self.readings_confirmed + self.readings_contradicted:
            raise ValueError("observer readings_given is smaller than its outcomes")

    @classmethod
    def from_mapping(cls, address: str, raw: Mapping[str, Any]) -> ObserverHistory:
        confirmed = _count(raw.get("readings_confirmed", 0), "readings_confirmed")
        contradicted = _count(raw.get("readings_contradicted", 0), "readings_contradicted")
        given_raw = raw.get("readings_given")
        given = confirmed + contradicted if given_raw is None else _count(given_raw, "readings_given")
        return cls(address, given, confirmed, contradicted)

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
    independent_operator_ids: tuple[str, ...] = ()
    independent_source_ids: tuple[str, ...] = ()
    independent_extractor_ids: tuple[str, ...] = ()
    freshness_checked: bool = False
    stale_observation_uids: tuple[str, ...] = ()

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
            "independent_operator_ids": list(self.independent_operator_ids),
            "independent_source_ids": list(self.independent_source_ids),
            "independent_extractor_ids": list(self.independent_extractor_ids),
            "freshness_checked": self.freshness_checked,
            "stale_observation_uids": list(self.stale_observation_uids),
        }


@dataclass(frozen=True)
class _Observation:
    value: Any
    source_type: str
    observer_address: str | None
    observation_uid: str
    source_url: str | None
    publisher_id: str | None
    provenance: ObservationProvenance | None
    effective_from: int | None


def check_acceptance(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    observer_records: Mapping[str, Mapping[str, Any]],
    *,
    manual_approval: bool,
    policy: AcceptancePolicy,
    source_binding: Mapping[str, Any] | None = None,
    now_unix: int | None = None,
) -> AcceptanceResult:
    """Apply the configured policy without I/O or a model call."""

    key = _required_string(condition_key, "condition_key")
    if not isinstance(manual_approval, bool):
        raise ValueError("manual_approval must be true or false")
    normalized = tuple(_observation(key, raw) for raw in observations)
    binding = SourceBinding.from_mapping(source_binding) if source_binding is not None else None
    reasons: list[str] = []
    freshness_checked = policy.max_observation_age_seconds is not None and now_unix is not None
    stale_observation_uids: tuple[str, ...] = ()
    if freshness_checked:
        freshness = check_freshness(
            [
                {
                    "observation_uid": item.observation_uid,
                    "effective_from": item.effective_from,
                }
                for item in normalized
            ],
            now_unix=now_unix if now_unix is not None else 0,
            max_age_seconds=policy.max_observation_age_seconds
            if policy.max_observation_age_seconds is not None
            else 1,
        )
        reasons.extend(freshness.reasons)
        stale_observation_uids = tuple(
            sorted(
                set(freshness.stale_observation_uids)
                | set(freshness.missing_timestamp_uids)
                | set(freshness.future_timestamp_uids)
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

    distinct_values = {_canonical_json(item.value) for item in normalized}
    if len(distinct_values) > 1:
        reasons.append("The available observations disagree about the current value.")
    if not normalized:
        reasons.append("No observation is available for this condition.")

    accepted = not reasons
    return AcceptanceResult(
        condition_key=key,
        status=AcceptanceStatus.ACCEPTED if accepted else AcceptanceStatus.CONTESTED,
        accepted_value=normalized[0].value if accepted else None,
        vendor_primary_present=bool(trusted_vendor_primary),
        independent_observer_addresses=independent_addresses,
        manual_approval=manual_approval,
        observation_uids=tuple(sorted(item.observation_uid for item in normalized)),
        reasons=tuple(reasons),
        independent_operator_ids=operator_ids,
        independent_source_ids=source_ids,
        independent_extractor_ids=extractor_ids,
        freshness_checked=freshness_checked,
        stale_observation_uids=stale_observation_uids,
    )


def _observation(condition_key: str, raw: Mapping[str, Any]) -> _Observation:
    raw_key = raw.get("condition_key")
    if raw_key is not None and raw_key != condition_key:
        raise ValueError("observation condition_key does not match the requested condition")
    value = raw.get("value")
    if value is None:
        raise ValueError("observation value must be present")
    source_type = _required_string(raw.get("source_type"), "observation source_type")
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
        if (
            not isinstance(raw_effective_from, int)
            or isinstance(raw_effective_from, bool)
            or raw_effective_from < 0
        ):
            raise ValueError("effective_from must be a non-negative integer when supplied")
        effective_from = raw_effective_from
    return _Observation(
        value,
        source_type,
        observer_address,
        uid,
        source_url,
        publisher_id,
        provenance,
        effective_from,
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
