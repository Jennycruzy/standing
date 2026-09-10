"""Bitemporal evidence records and deterministic temporal resolution.

Standing has two different clocks for evidence:

* valid time describes when a fact applied in the outside world; and
* knowledge time describes when Standing recorded the observation.

This module is intentionally free of storage and network code.  It turns the
records returned by Sibyl or Base EAS into a deterministic temporal view that
can be tested independently of the reviewer and acceptance policy.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import time
from typing import Any, Mapping, Sequence, cast
from urllib.parse import urlparse


class TemporalObservationError(ValueError):
    """Raised when a bitemporal observation cannot be trusted or resolved."""


@dataclass(frozen=True)
class TemporalObservation:
    """One observation with separate valid-time and knowledge-time fields.

    The optional fields make it possible to read legacy observations without
    pretending that they are bitemporal.  ``strict=True`` in
    :meth:`from_mapping` requires every field needed for a new governed
    observation.
    """

    condition_key: str
    value: Any
    value_type: str | None
    unit: str | None
    effective_from: int | None
    effective_until: int | None
    observed_at: int | None
    recorded_at: int | None
    source_url: str | None
    source_domain: str | None
    source_type: str
    attester: str | None
    operator_id: str | None
    extraction_method: str | None
    extraction_version: str | None
    observation_uid: str
    ref_uid: str | None
    evidence_hash: str | None
    notes: str
    source_document_hash: str | None = None
    source_snapshot_hash: str | None = None
    source_publication_date: int | None = None
    confidence: float | None = None
    revoked: bool = False
    accepted: bool | None = None
    demo_controlled: bool = False
    observer_address: str | None = None
    publisher_id: str | None = None
    provenance: Mapping[str, Any] | None = None
    block_number: int | None = None
    knowledge_recorded_by: str | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        strict: bool = True,
        expected_condition_key: str | None = None,
    ) -> TemporalObservation:
        """Parse one observation and validate its bitemporal shape.

        ``strict=False`` is only a compatibility reader for pre-temporal
        records.  Such records remain explicitly incomplete and cannot be used
        by temporal queries.
        """

        if not isinstance(raw, Mapping):
            raise TemporalObservationError("observation must be an object")
        condition_key = _required_string(raw.get("condition_key"), "condition_key")
        if expected_condition_key is not None and condition_key != expected_condition_key:
            raise TemporalObservationError("observation condition_key does not match the requested condition")
        value = raw.get("value")
        if value is None:
            raise TemporalObservationError("observation value must be present")

        value_type = _optional_string(raw.get("value_type"), "value_type")
        unit = _optional_string(raw.get("unit"), "unit")
        effective_from = _optional_timestamp(raw.get("effective_from"), "effective_from")
        effective_until = _optional_timestamp(raw.get("effective_until"), "effective_until")
        observed_at = _optional_timestamp(raw.get("observed_at"), "observed_at")
        recorded_at = _optional_timestamp(raw.get("recorded_at"), "recorded_at")
        knowledge_recorded_by = _optional_string(
            raw.get("knowledge_recorded_by"), "knowledge_recorded_by"
        )

        raw_source_url = raw.get("source_url")
        source_url = _optional_url(raw_source_url, "source_url")
        derived_domain = _source_domain(source_url) if source_url is not None else None
        source_domain = _optional_string(raw.get("source_domain"), "source_domain")
        if source_domain is not None:
            source_domain = _normalize_domain(source_domain)
            if derived_domain is not None and source_domain != derived_domain:
                raise TemporalObservationError("source_domain does not match source_url")
        else:
            source_domain = derived_domain

        source_type = _required_string(raw.get("source_type"), "source_type")
        attester = _optional_string(raw.get("attester"), "attester")
        operator_id = _optional_string(raw.get("operator_id"), "operator_id")
        extraction_method = _optional_string(raw.get("extraction_method"), "extraction_method")
        extraction_version = _optional_string(raw.get("extraction_version"), "extraction_version")
        observation_uid = _required_string(raw.get("observation_uid"), "observation_uid")
        ref_uid = _optional_uid(raw.get("ref_uid"), "ref_uid")
        evidence_hash = _optional_hash(raw.get("evidence_hash"), "evidence_hash")
        notes_raw = raw.get("notes", raw.get("note", ""))
        if not isinstance(notes_raw, str):
            raise TemporalObservationError("notes must be a string")
        notes = notes_raw.strip()

        source_document_hash = _optional_hash(raw.get("source_document_hash"), "source_document_hash")
        source_snapshot_hash = _optional_hash(raw.get("source_snapshot_hash"), "source_snapshot_hash")
        source_publication_date = _optional_timestamp(
            raw.get("source_publication_date"), "source_publication_date"
        )
        confidence = _optional_confidence(raw.get("confidence"))
        revoked_value = _optional_bool(raw.get("revoked", raw.get("is_revoked", False)), "revoked")
        revoked = False if revoked_value is None else revoked_value
        accepted = _optional_bool(raw.get("accepted"), "accepted")
        demo_value = _optional_bool(raw.get("demo_controlled", False), "demo_controlled")
        demo_controlled = False if demo_value is None else demo_value
        observer_address = _optional_string(raw.get("observer_address"), "observer_address")
        publisher_id = _optional_string(raw.get("publisher_id"), "publisher_id")
        provenance = raw.get("provenance")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise TemporalObservationError("provenance must be an object when supplied")
        block_number = _optional_nonnegative_int(raw.get("block_number"), "block_number")

        result = cls(
            condition_key=condition_key,
            value=value,
            value_type=value_type,
            unit=unit,
            effective_from=effective_from,
            effective_until=effective_until,
            observed_at=observed_at,
            recorded_at=recorded_at,
            source_url=source_url,
            source_domain=source_domain,
            source_type=source_type,
            attester=attester,
            operator_id=operator_id,
            extraction_method=extraction_method,
            extraction_version=extraction_version,
            observation_uid=observation_uid,
            ref_uid=ref_uid,
            evidence_hash=evidence_hash,
            notes=notes,
            source_document_hash=source_document_hash,
            source_snapshot_hash=source_snapshot_hash,
            source_publication_date=source_publication_date,
            confidence=confidence,
            revoked=revoked,
            accepted=accepted,
            demo_controlled=demo_controlled,
            observer_address=observer_address,
            publisher_id=publisher_id,
            provenance=dict(provenance) if isinstance(provenance, Mapping) else None,
            block_number=block_number,
            knowledge_recorded_by=knowledge_recorded_by,
        )
        result.validate(strict=strict)
        return result

    @property
    def is_bitemporal(self) -> bool:
        """Whether both valid-time and knowledge-time fields are complete."""

        return (
            self.effective_from is not None
            and self.observed_at is not None
            and self.recorded_at is not None
        )

    @property
    def is_complete(self) -> bool:
        """Whether all fields required for a new governed observation exist."""

        return self.is_bitemporal and all(
            value is not None
            for value in (
                self.value_type,
                self.unit,
                self.source_url,
                self.source_domain,
                self.attester,
                self.operator_id,
                self.extraction_method,
                self.extraction_version,
                self.evidence_hash,
            )
        )

    def validate(self, *, strict: bool) -> None:
        """Validate relationships and required fields without doing I/O."""

        if self.effective_until is not None and self.effective_from is not None:
            if self.effective_until <= self.effective_from:
                raise TemporalObservationError("effective_until must be after effective_from")
        if self.observed_at is not None and self.recorded_at is not None:
            if self.recorded_at < self.observed_at:
                raise TemporalObservationError("recorded_at must not precede observed_at")
        if strict:
            missing = [
                name
                for name, value in (
                    ("value_type", self.value_type),
                    ("unit", self.unit),
                    ("effective_from", self.effective_from),
                    ("observed_at", self.observed_at),
                    ("recorded_at", self.recorded_at),
                    ("source_url", self.source_url),
                    ("source_domain", self.source_domain),
                    ("attester", self.attester),
                    ("operator_id", self.operator_id),
                    ("extraction_method", self.extraction_method),
                    ("extraction_version", self.extraction_version),
                    ("evidence_hash", self.evidence_hash),
                )
                if value is None
            ]
            if missing:
                raise TemporalObservationError(
                    "bitemporal observation is missing required field(s): " + ", ".join(missing)
                )
            self._validate_typed_value()

    def _validate_typed_value(self) -> None:
        """Validate the serialized value before it can become governed evidence."""

        if self.value_type not in {"number", "boolean", "date", "set"}:
            raise TemporalObservationError(f"unsupported observation value_type: {self.value_type}")
        if self.value_type == "number":
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise TemporalObservationError("number observation value must be numeric")
            if not math.isfinite(float(self.value)):
                raise TemporalObservationError("number observation value must be finite")
        elif self.value_type == "boolean":
            if not isinstance(self.value, bool):
                raise TemporalObservationError("boolean observation value must be boolean")
        elif self.value_type == "date":
            if not isinstance(self.value, str):
                raise TemporalObservationError("date observation value must be an ISO date")
            try:
                date.fromisoformat(self.value)
            except ValueError as error:
                raise TemporalObservationError("date observation value must be an ISO date") from error
        elif (
            not isinstance(self.value, Sequence)
            or isinstance(self.value, (str, bytes))
            or any(not isinstance(item, str) for item in self.value)
        ):
            raise TemporalObservationError("set observation value must be a list of strings")

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible record without losing temporal metadata."""

        result: dict[str, Any] = {
            "condition_key": self.condition_key,
            "value": self.value,
            "value_type": self.value_type,
            "unit": self.unit,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "knowledge_recorded_by": self.knowledge_recorded_by,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "source_type": self.source_type,
            "attester": self.attester,
            "operator_id": self.operator_id,
            "extraction_method": self.extraction_method,
            "extraction_version": self.extraction_version,
            "observation_uid": self.observation_uid,
            "ref_uid": self.ref_uid,
            "evidence_hash": self.evidence_hash,
            "notes": self.notes,
            "source_document_hash": self.source_document_hash,
            "source_snapshot_hash": self.source_snapshot_hash,
            "source_publication_date": self.source_publication_date,
            "confidence": self.confidence,
            "revoked": self.revoked,
            "accepted": self.accepted,
            "demo_controlled": self.demo_controlled,
        }
        if self.observer_address is not None:
            result["observer_address"] = self.observer_address
        if self.publisher_id is not None:
            result["publisher_id"] = self.publisher_id
        if self.provenance is not None:
            result["provenance"] = dict(self.provenance)
        if self.block_number is not None:
            result["block_number"] = self.block_number
        return result


@dataclass(frozen=True)
class TemporalResolution:
    """The deterministic answer for one temporal evidence query."""

    condition_key: str
    valid_at: int
    knowledge_at: int | None
    history: tuple[TemporalObservation, ...]
    active: tuple[TemporalObservation, ...]
    candidates: tuple[TemporalObservation, ...]
    current: TemporalObservation | None
    conflict: bool
    conflicting_uids: tuple[str, ...]
    superseded_uids: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def accepted_value(self) -> Any:
        """Return the canonical value, or ``None`` when contested/unknown."""

        return None if self.current is None else self.current.value

    @property
    def observation_uids(self) -> tuple[str, ...]:
        """Return the evidence UIDs used by the resolution."""

        return tuple(item.observation_uid for item in self.candidates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "valid_at": self.valid_at,
            "knowledge_at": self.knowledge_at,
            "history": [item.as_dict() for item in self.history],
            "active": [item.observation_uid for item in self.active],
            "candidates": [item.observation_uid for item in self.candidates],
            "current": None if self.current is None else self.current.as_dict(),
            "conflict": self.conflict,
            "conflicting_uids": list(self.conflicting_uids),
            "superseded_uids": list(self.superseded_uids),
            "reasons": list(self.reasons),
        }


class TemporalEvidence:
    """Pure resolver for observations belonging to one condition."""

    def __init__(self, observations: Sequence[TemporalObservation]) -> None:
        self.observations = tuple(observations)
        keys = {item.condition_key for item in self.observations}
        if len(keys) > 1:
            raise TemporalObservationError("temporal evidence cannot mix condition keys")
        uids = [item.observation_uid for item in self.observations]
        if len(set(uids)) != len(uids):
            raise TemporalObservationError("observation UIDs must be unique")

    @classmethod
    def from_mappings(
        cls,
        observations: Sequence[Mapping[str, Any]],
        *,
        strict: bool = True,
        condition_key: str | None = None,
    ) -> TemporalEvidence:
        parsed = tuple(
            TemporalObservation.from_mapping(
                item,
                strict=strict,
                expected_condition_key=condition_key,
            )
            for item in observations
        )
        return cls(parsed)

    @property
    def condition_key(self) -> str | None:
        return self.observations[0].condition_key if self.observations else None

    @property
    def is_bitemporal(self) -> bool:
        """Whether every record has at least valid and knowledge time."""

        return bool(self.observations) and all(item.is_bitemporal for item in self.observations)

    @property
    def is_complete(self) -> bool:
        """Whether every record meets the strict new-observation contract."""

        return bool(self.observations) and all(item.is_complete for item in self.observations)

    def resolve(
        self,
        *,
        valid_at: int | date | datetime | str | None = None,
        knowledge_at: int | date | datetime | str | None = None,
        accepted_only: bool = False,
    ) -> TemporalResolution:
        """Resolve the canonical fact at a valid-time/knowledge-time point.

        A newer *effective* observation is a change, not a conflict.  A
        conflict exists only when incompatible observations remain at the same
        winning effective time after supersession and revocation are applied.
        """

        self._require_temporal()
        valid_timestamp = _timestamp_or_now(valid_at)
        knowledge_timestamp = (
            None if knowledge_at is None else _coerce_timestamp(knowledge_at, "knowledge_at")
        )
        known = tuple(
            item
            for item in self.observations
            # ``accepted_only`` is a governance query, not a compatibility
            # query. Unknown/legacy acceptance is deliberately excluded;
            # only an explicit promotion may make a row eligible here.
            if (not accepted_only or item.accepted is True)
            and (
                knowledge_timestamp is None
                or item.recorded_at is not None
                and item.recorded_at <= knowledge_timestamp
            )
        )
        history = tuple(
            sorted(
                known,
                key=lambda item: (
                    _sort_timestamp(item.effective_from),
                    _sort_timestamp(item.recorded_at),
                    item.observation_uid,
                ),
            )
        )
        # Revocation removes evidence from the canonical head, but never from
        # the historical ledger. A revoked parent must also not be allowed to
        # create a supersession edge for a current child.
        available = tuple(item for item in known if not item.revoked)
        by_uid = {item.observation_uid: item for item in available}
        children: dict[str, list[TemporalObservation]] = {}
        for item in available:
            if item.ref_uid is None:
                continue
            parent = by_uid.get(item.ref_uid)
            if parent is None:
                continue
            if item.effective_from is None or parent.effective_from is None:
                continue
            if item.effective_from < parent.effective_from:
                raise TemporalObservationError(
                    f"observation {item.observation_uid} supersedes an observation from a later period"
                )
            children.setdefault(parent.observation_uid, []).append(item)

        active: list[TemporalObservation] = []
        superseded: set[str] = set()
        for item in available:
            if item.effective_from is None:
                continue
            end = item.effective_until
            for child in children.get(item.observation_uid, []):
                if child.effective_from is not None:
                    end = child.effective_from if end is None else min(end, child.effective_from)
            if end is not None and valid_timestamp >= end:
                superseded.add(item.observation_uid)
                continue
            if item.effective_from <= valid_timestamp:
                active.append(item)

        if not active:
            return TemporalResolution(
                condition_key=self.condition_key or "",
                valid_at=valid_timestamp,
                knowledge_at=knowledge_timestamp,
                history=history,
                active=(),
                candidates=(),
                current=None,
                conflict=False,
                conflicting_uids=(),
                superseded_uids=tuple(sorted(superseded)),
                reasons=("No observation covers the requested valid-time point.",),
            )

        winning_effective = max(
            item.effective_from for item in active if item.effective_from is not None
        )
        candidates = tuple(
            sorted(
                (item for item in active if item.effective_from == winning_effective),
                key=lambda item: (
                    _sort_timestamp(item.recorded_at),
                    _sort_timestamp(item.observed_at),
                    item.observation_uid,
                ),
            )
        )
        distinct_values = {_canonical_json(item.value) for item in candidates}
        conflict = len(distinct_values) > 1
        current: TemporalObservation | None = None
        reasons: list[str] = []
        if conflict:
            reasons.append("Incompatible observations share the same effective period.")
        elif candidates:
            current = candidates[-1]
        return TemporalResolution(
            condition_key=self.condition_key or "",
            valid_at=valid_timestamp,
            knowledge_at=knowledge_timestamp,
            history=history,
            active=tuple(
                sorted(
                    active,
                    key=lambda item: (
                        _sort_timestamp(item.effective_from),
                        item.observation_uid,
                    ),
                )
            ),
            candidates=candidates,
            current=current,
            conflict=conflict,
            conflicting_uids=tuple(item.observation_uid for item in candidates) if conflict else (),
            superseded_uids=tuple(sorted(superseded)),
            reasons=tuple(reasons),
        )

    def current(
        self,
        *,
        as_of: int | date | datetime | str | None = None,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Return the canonical current observation, or ``None`` on conflict."""

        return self.resolve(valid_at=as_of, accepted_only=accepted_only).current

    def valid_as_of(
        self,
        valid_at: int | date | datetime | str,
        *,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Return what is now believed to have been valid at a past instant."""

        return self.resolve(valid_at=valid_at, accepted_only=accepted_only).current

    def known_as_of(
        self,
        knowledge_at: int | date | datetime | str,
        *,
        valid_at: int | date | datetime | str | None = None,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Return the fact Standing could have selected using then-known data."""

        point = knowledge_at if valid_at is None else valid_at
        return self.resolve(
            valid_at=point,
            knowledge_at=knowledge_at,
            accepted_only=accepted_only,
        ).current

    def history(
        self,
        *,
        knowledge_at: int | date | datetime | str | None = None,
        accepted_only: bool = False,
    ) -> tuple[TemporalObservation, ...]:
        """Return the evidence chain without erasing superseded observations."""

        self._require_temporal()
        cutoff = None if knowledge_at is None else _coerce_timestamp(knowledge_at, "knowledge_at")
        known = tuple(
            sorted(
                (
                    item
                    for item in self.observations
                    if (not accepted_only or item.accepted is True)
                    and (cutoff is None or item.recorded_at is not None and item.recorded_at <= cutoff)
                ),
                key=lambda item: (
                    _sort_timestamp(item.effective_from),
                    _sort_timestamp(item.recorded_at),
                    item.observation_uid,
                ),
            )
        )
        return known

    def _require_temporal(self) -> None:
        missing: set[str] = set()
        for item in self.observations:
            for name, present in (
                ("effective_from", item.effective_from is not None),
                ("observed_at", item.observed_at is not None),
                ("recorded_at", item.recorded_at is not None),
            ):
                if not present:
                    missing.add(name)
        if missing:
            raise TemporalObservationError(
                "temporal query requires complete valid/knowledge time; missing " + ", ".join(missing)
            )


def current(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: int | date | datetime | str | None = None,
    accepted_only: bool = True,
) -> TemporalObservation | None:
    """Resolve ``current(condition_key)`` from serialized observations."""

    evidence = TemporalEvidence.from_mappings(observations, condition_key=condition_key)
    return evidence.current(as_of=as_of, accepted_only=accepted_only)


def valid_as_of(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    valid_at: int | date | datetime | str,
    *,
    accepted_only: bool = True,
) -> TemporalObservation | None:
    """Resolve ``valid_as_of(condition_key, date)``."""

    evidence = TemporalEvidence.from_mappings(observations, condition_key=condition_key)
    return evidence.valid_as_of(valid_at, accepted_only=accepted_only)


def known_as_of(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    knowledge_at: int | date | datetime | str,
    *,
    valid_at: int | date | datetime | str | None = None,
    accepted_only: bool = True,
) -> TemporalObservation | None:
    """Resolve ``known_as_of(condition_key, date)``."""

    evidence = TemporalEvidence.from_mappings(observations, condition_key=condition_key)
    return evidence.known_as_of(
        knowledge_at,
        valid_at=valid_at,
        accepted_only=accepted_only,
    )


def history(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    knowledge_at: int | date | datetime | str | None = None,
    accepted_only: bool = False,
) -> tuple[TemporalObservation, ...]:
    """Resolve ``history(condition_key)``."""

    evidence = TemporalEvidence.from_mappings(observations, condition_key=condition_key)
    return evidence.history(knowledge_at=knowledge_at, accepted_only=accepted_only)


def observation_evidence_hash(payload: Mapping[str, Any]) -> str:
    """Hash a source-derived payload for reproducible observation identity."""

    encoded = json.dumps(
        _stable_value(dict(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_timestamp(value: int | date | datetime | str, *, label: str = "timestamp") -> int:
    """Parse a Unix timestamp or ISO date into UTC seconds."""

    return _coerce_timestamp(value, label)


def _timestamp_or_now(value: int | date | datetime | str | None) -> int:
    return int(time()) if value is None else _coerce_timestamp(value, "valid_at")


def _coerce_timestamp(value: int | date | datetime | str, label: str) -> int:
    if isinstance(value, bool):
        raise TemporalObservationError(f"{label} must be a timestamp or ISO date")
    if isinstance(value, int):
        if value < 0:
            raise TemporalObservationError(f"{label} must be non-negative")
        return value
    if isinstance(value, datetime):
        parsed_datetime = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return int(parsed_datetime.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TemporalObservationError(f"{label} must not be empty")
        try:
            parsed_date = date.fromisoformat(text)
            return int(datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc).timestamp())
        except ValueError:
            try:
                parsed_datetime = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as error:
                raise TemporalObservationError(f"{label} must be a timestamp or ISO date") from error
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
            return int(parsed_datetime.timestamp())
    raise TemporalObservationError(f"{label} must be a timestamp or ISO date")


def _optional_timestamp(value: Any, label: str) -> int | None:
    return None if value is None else _coerce_timestamp(value, label)


def _sort_timestamp(value: int | None) -> int:
    return -1 if value is None else value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemporalObservationError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def _optional_url(value: Any, label: str) -> str | None:
    if value is None:
        return None
    url = _required_string(value, label)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise TemporalObservationError(f"{label} must be an HTTP or HTTPS URL")
    return url


def _source_domain(url: str | None) -> str | None:
    if url is None:
        return None
    hostname = urlparse(url).hostname
    return None if hostname is None else _normalize_domain(hostname)


def _normalize_domain(value: str) -> str:
    return _required_string(value, "source_domain").lower().rstrip(".")


def _optional_uid(value: Any, label: str) -> str | None:
    uid = _optional_string(value, label)
    if uid is not None and uid.lower() == "0x" + "0" * 64:
        return None
    return uid


def _optional_hash(value: Any, label: str) -> str | None:
    raw = _optional_string(value, label)
    if raw is None:
        return None
    normalized = raw.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise TemporalObservationError(f"{label} must be a 64-character hexadecimal SHA-256 hash")
    return normalized


def _optional_confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemporalObservationError("confidence must be a number between 0 and 1")
    result = float(value)
    if not 0 <= result <= 1:
        raise TemporalObservationError("confidence must be a number between 0 and 1")
    return result


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TemporalObservationError(f"{label} must be true or false")
    return value


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TemporalObservationError(f"{label} must be a non-negative integer")
    if value < 0:
        raise TemporalObservationError(f"{label} must be a non-negative integer")
    return cast(int, value)


def _canonical_json(value: Any) -> str:
    return json.dumps(_stable_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _stable_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_stable_value(item) for item in value), key=_canonical_json)
    raise TemporalObservationError(f"value of type {type(value).__name__} cannot be serialized")
