"""Pure decision history, remediation, waiver, and time-travel primitives.

The evaluator answers what the current evidence says.  This module answers
which decision revision governed at a point in time and whether a human may
temporarily continue while remediation is in progress.  It has no memory,
network, or model dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence


class LifecycleError(ValueError):
    """Raised when a lifecycle record or transition is invalid."""


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def _unix_time(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise LifecycleError(f"{label} must be a Unix timestamp or an ISO-8601 timestamp")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp < 0:
            raise LifecycleError(f"{label} must be a finite, non-negative timestamp")
        return timestamp
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise LifecycleError(f"{label} must be a valid ISO-8601 timestamp") from error
        if parsed.tzinfo is None:
            raise LifecycleError(f"{label} must include a timezone")
        timestamp = parsed.timestamp()
        if not math.isfinite(timestamp) or timestamp < 0:
            raise LifecycleError(f"{label} must be a finite, non-negative timestamp")
        return timestamp
    raise LifecycleError(f"{label} must be a Unix timestamp or an ISO-8601 timestamp")


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class DecisionRevision:
    """One immutable version of a decision and the revision it supersedes."""

    decision_id: str
    revision_id: str
    body: dict[str, Any]
    effective_from: int
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id.strip():
            raise LifecycleError("decision_id must not be empty")
        if not self.revision_id.strip():
            raise LifecycleError("revision_id must not be empty")
        if not isinstance(self.body, dict):
            raise LifecycleError("revision body must be a mapping")
        _nonnegative_int(self.effective_from, "effective_from")
        if self.supersedes_revision_id is not None and not self.supersedes_revision_id.strip():
            raise LifecycleError("supersedes_revision_id must not be empty when supplied")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DecisionRevision:
        """Parse a stored revision row with its body either nested or inline."""

        if not isinstance(raw, Mapping):
            raise LifecycleError("decision revision must be a mapping")
        nested_body = raw.get("body")
        if nested_body is None:
            body = dict(raw)
        elif isinstance(nested_body, Mapping):
            body = dict(nested_body)
        else:
            raise LifecycleError("decision revision body must be a mapping")

        decision_id = raw.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            decision_id = body.get("decision_id", body.get("id"))
        revision_id = _required_string(raw.get("revision_id"), "revision_id")
        effective_from = _nonnegative_int(raw.get("effective_from"), "effective_from")
        supersedes = _optional_string(raw.get("supersedes_revision_id"), "supersedes_revision_id")
        parsed_decision_id = _required_string(decision_id, "decision_id")
        body_decision_id = body.get("decision_id")
        if body_decision_id is not None and _required_string(body_decision_id, "body.decision_id") != parsed_decision_id:
            raise LifecycleError("revision decision_id does not match its body")
        body["decision_id"] = parsed_decision_id
        body["revision_id"] = revision_id
        return cls(parsed_decision_id, revision_id, body, effective_from, supersedes)

    def materialized_body(self) -> dict[str, Any]:
        """Return the decision body with stable revision identity included."""

        body = dict(self.body)
        body["decision_id"] = self.decision_id
        body["revision_id"] = self.revision_id
        return body

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "revision_id": self.revision_id,
            "effective_from": self.effective_from,
            "supersedes_revision_id": self.supersedes_revision_id,
            "body": self.materialized_body(),
        }


@dataclass(frozen=True)
class RevisionTimeline:
    """The valid revision chain and the revision active at ``as_of``."""

    decision_id: str
    as_of: int | None
    revisions: tuple[DecisionRevision, ...]
    active_revision: DecisionRevision | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "as_of": self.as_of,
            "active_revision": None if self.active_revision is None else self.active_revision.as_dict(),
            "revisions": [revision.as_dict() for revision in self.revisions],
        }


def build_revision_timeline(
    decision_id: str,
    revisions: Sequence[Mapping[str, Any]],
    *,
    as_of: int | None = None,
) -> RevisionTimeline:
    """Validate a single rooted revision chain and select its active version."""

    key = _required_string(decision_id, "decision_id")
    if as_of is not None:
        _nonnegative_int(as_of, "as_of")
    parsed = tuple(DecisionRevision.from_mapping(raw) for raw in revisions)
    if not parsed:
        raise LifecycleError(f"no revisions are available for decision {key}")
    if any(revision.decision_id != key for revision in parsed):
        raise LifecycleError("all revisions must belong to the requested decision")

    by_id: dict[str, DecisionRevision] = {}
    for revision in parsed:
        if revision.revision_id in by_id:
            raise LifecycleError(f"duplicate revision_id {revision.revision_id}")
        by_id[revision.revision_id] = revision

    roots = [revision for revision in parsed if revision.supersedes_revision_id is None]
    if len(roots) != 1:
        raise LifecycleError("a decision revision chain must have exactly one root")

    children: dict[str, list[str]] = {}
    for revision in parsed:
        parent_id = revision.supersedes_revision_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            raise LifecycleError(
                f"revision {revision.revision_id} supersedes missing revision {parent_id}"
            )
        if parent.effective_from >= revision.effective_from:
            raise LifecycleError(
                f"revision {revision.revision_id} must become effective after {parent_id}"
            )
        children.setdefault(parent_id, []).append(revision.revision_id)

    for parent_id, child_ids in children.items():
        if len(child_ids) > 1:
            raise LifecycleError(f"revision {parent_id} has more than one successor")

    ordered = tuple(sorted(parsed, key=lambda item: (item.effective_from, item.revision_id)))
    effective_as_of = max(revision.effective_from for revision in ordered) if as_of is None else as_of
    eligible = [revision for revision in ordered if revision.effective_from <= effective_as_of]
    active = eligible[-1] if eligible else None
    return RevisionTimeline(key, as_of, ordered, active)


class RemediationStatus(StrEnum):
    """States in the human-visible remediation lifecycle."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class Remediation:
    """An auditable remediation record tied to a decision revision."""

    remediation_id: str
    decision_id: str
    revision_id: str
    status: RemediationStatus
    opened_at: int
    updated_at: int
    summary: str
    resolution_reason: str | None = None
    superseded_by_revision_id: str | None = None

    def __post_init__(self) -> None:
        _required_string(self.remediation_id, "remediation_id")
        _required_string(self.decision_id, "decision_id")
        _required_string(self.revision_id, "revision_id")
        if not isinstance(self.status, RemediationStatus):
            raise LifecycleError("status must be a RemediationStatus")
        _nonnegative_int(self.opened_at, "opened_at")
        _nonnegative_int(self.updated_at, "updated_at")
        if self.updated_at < self.opened_at:
            raise LifecycleError("updated_at cannot precede opened_at")
        _required_string(self.summary, "summary")
        if self.status in {RemediationStatus.RESOLVED, RemediationStatus.SUPERSEDED}:
            _required_string(self.resolution_reason, "resolution_reason")
        if self.status == RemediationStatus.SUPERSEDED:
            _required_string(self.superseded_by_revision_id, "superseded_by_revision_id")
        elif self.superseded_by_revision_id is not None:
            raise LifecycleError("only a superseded remediation may name a successor revision")

    @classmethod
    def create(
        cls,
        remediation_id: str,
        decision_id: str,
        revision_id: str,
        *,
        opened_at: int,
        summary: str,
    ) -> Remediation:
        return cls(
            _required_string(remediation_id, "remediation_id"),
            _required_string(decision_id, "decision_id"),
            _required_string(revision_id, "revision_id"),
            RemediationStatus.OPEN,
            _nonnegative_int(opened_at, "opened_at"),
            _nonnegative_int(opened_at, "opened_at"),
            _required_string(summary, "summary"),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Remediation:
        if not isinstance(raw, Mapping):
            raise LifecycleError("remediation must be a mapping")
        status_raw = _required_string(raw.get("status"), "status")
        try:
            status = RemediationStatus(status_raw)
        except ValueError as error:
            raise LifecycleError(f"unknown remediation status {status_raw}") from error
        return cls(
            _required_string(raw.get("remediation_id"), "remediation_id"),
            _required_string(raw.get("decision_id"), "decision_id"),
            _required_string(raw.get("revision_id"), "revision_id"),
            status,
            _nonnegative_int(raw.get("opened_at"), "opened_at"),
            _nonnegative_int(raw.get("updated_at"), "updated_at"),
            _required_string(raw.get("summary"), "summary"),
            _optional_string(raw.get("resolution_reason"), "resolution_reason"),
            _optional_string(raw.get("superseded_by_revision_id"), "superseded_by_revision_id"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "remediation_id": self.remediation_id,
            "decision_id": self.decision_id,
            "revision_id": self.revision_id,
            "status": self.status.value,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "resolution_reason": self.resolution_reason,
            "superseded_by_revision_id": self.superseded_by_revision_id,
        }


@dataclass(frozen=True)
class RemediationTransition:
    """One valid state transition and its resulting remediation record."""

    from_status: RemediationStatus
    to_status: RemediationStatus
    occurred_at: int
    actor_id: str
    reason: str
    remediation: Remediation

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "occurred_at": self.occurred_at,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "remediation": self.remediation.as_dict(),
        }


_REMEDIATION_TRANSITIONS: dict[RemediationStatus, frozenset[RemediationStatus]] = {
    RemediationStatus.OPEN: frozenset(
        {RemediationStatus.IN_PROGRESS, RemediationStatus.RESOLVED, RemediationStatus.SUPERSEDED}
    ),
    RemediationStatus.IN_PROGRESS: frozenset(
        {RemediationStatus.OPEN, RemediationStatus.RESOLVED, RemediationStatus.SUPERSEDED}
    ),
    RemediationStatus.RESOLVED: frozenset({RemediationStatus.OPEN, RemediationStatus.SUPERSEDED}),
    RemediationStatus.SUPERSEDED: frozenset(),
}


def transition_remediation(
    remediation: Remediation,
    target_status: RemediationStatus | str,
    *,
    occurred_at: int,
    actor_id: str,
    reason: str,
    superseded_by_revision_id: str | None = None,
) -> RemediationTransition:
    """Apply one explicitly justified remediation transition."""

    if isinstance(target_status, str):
        try:
            target = RemediationStatus(target_status)
        except ValueError as error:
            raise LifecycleError(f"unknown remediation status {target_status}") from error
    else:
        target = target_status
    if not isinstance(target, RemediationStatus):
        raise LifecycleError("target_status must be a RemediationStatus")
    if target not in _REMEDIATION_TRANSITIONS[remediation.status]:
        raise LifecycleError(
            f"cannot transition remediation from {remediation.status.value} to {target.value}"
        )
    when = _nonnegative_int(occurred_at, "occurred_at")
    if when < remediation.updated_at:
        raise LifecycleError("occurred_at cannot precede the last remediation update")
    actor = _required_string(actor_id, "actor_id")
    explanation = _required_string(reason, "reason")
    successor = _optional_string(superseded_by_revision_id, "superseded_by_revision_id")
    if target == RemediationStatus.SUPERSEDED and successor is None:
        raise LifecycleError("superseding a remediation requires a successor revision")
    if target != RemediationStatus.SUPERSEDED and successor is not None:
        raise LifecycleError("only a superseded transition may name a successor revision")
    resolution_reason = explanation if target in {RemediationStatus.RESOLVED, RemediationStatus.SUPERSEDED} else None
    updated = Remediation(
        remediation.remediation_id,
        remediation.decision_id,
        remediation.revision_id,
        target,
        remediation.opened_at,
        when,
        remediation.summary,
        resolution_reason,
        successor,
    )
    return RemediationTransition(remediation.status, target, when, actor, explanation, updated)


@dataclass(frozen=True)
class Waiver:
    """A temporary human authorization that never changes the factual result."""

    waiver_id: str
    decision_id: str
    condition_key: str | None
    reason: str
    issued_by: str
    issuer_role: str
    issued_at: int
    expires_at: int

    def __post_init__(self) -> None:
        _required_string(self.waiver_id, "waiver_id")
        _required_string(self.decision_id, "decision_id")
        _optional_string(self.condition_key, "condition_key")
        _required_string(self.reason, "reason")
        _required_string(self.issued_by, "issued_by")
        if self.issuer_role.strip().lower() != "human":
            raise LifecycleError("only a human may issue a waiver")
        _nonnegative_int(self.issued_at, "issued_at")
        _nonnegative_int(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise LifecycleError("expires_at must be after issued_at")

    def is_active(self, now_unix: int) -> bool:
        """Return whether the waiver is active; expiry automatically restores the gate."""

        now = _nonnegative_int(now_unix, "now_unix")
        return self.issued_at <= now < self.expires_at

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Waiver:
        if not isinstance(raw, Mapping):
            raise LifecycleError("waiver must be a mapping")
        return cls(
            _required_string(raw.get("waiver_id"), "waiver_id"),
            _required_string(raw.get("decision_id"), "decision_id"),
            _optional_string(raw.get("condition_key"), "condition_key"),
            _required_string(raw.get("reason"), "reason"),
            _required_string(raw.get("issued_by"), "issued_by"),
            _required_string(raw.get("issuer_role"), "issuer_role"),
            _nonnegative_int(raw.get("issued_at"), "issued_at"),
            _nonnegative_int(raw.get("expires_at"), "expires_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "waiver_id": self.waiver_id,
            "decision_id": self.decision_id,
            "condition_key": self.condition_key,
            "reason": self.reason,
            "issued_by": self.issued_by,
            "issuer_role": self.issuer_role,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


def issue_waiver(
    waiver_id: str,
    decision_id: str,
    *,
    condition_key: str | None,
    reason: str,
    issued_by: str,
    issuer_role: str,
    issued_at: int,
    expires_at: int,
) -> Waiver:
    """Create a waiver and enforce the human-only issuer boundary."""

    return Waiver(
        _required_string(waiver_id, "waiver_id"),
        _required_string(decision_id, "decision_id"),
        _optional_string(condition_key, "condition_key"),
        _required_string(reason, "reason"),
        _required_string(issued_by, "issued_by"),
        _required_string(issuer_role, "issuer_role"),
        _nonnegative_int(issued_at, "issued_at"),
        _nonnegative_int(expires_at, "expires_at"),
    )


@dataclass(frozen=True)
class WaiverCheck:
    """The action-gate result for a waiver at one instant."""

    waiver_id: str | None
    active: bool
    permits_action: bool
    automatically_restored: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "waiver_id": self.waiver_id,
            "active": self.active,
            "permits_action": self.permits_action,
            "automatically_restored": self.automatically_restored,
            "reason": self.reason,
        }


def check_waiver(
    waiver: Waiver | None,
    *,
    decision_id: str,
    blocking_condition_keys: Sequence[str],
    now_unix: int,
) -> WaiverCheck:
    """Check scope and expiry without altering the evaluator's standing state."""

    key = _required_string(decision_id, "decision_id")
    now = _nonnegative_int(now_unix, "now_unix")
    blocking = {_required_string(item, "blocking condition key") for item in blocking_condition_keys}
    if waiver is None:
        return WaiverCheck(None, False, False, False, "No waiver is present.")
    if waiver.decision_id != key:
        return WaiverCheck(
            waiver.waiver_id,
            False,
            False,
            False,
            "The waiver does not cover this decision.",
        )
    if waiver.condition_key is not None and waiver.condition_key not in blocking:
        return WaiverCheck(
            waiver.waiver_id,
            False,
            False,
            False,
            "The waiver does not cover a currently blocking condition.",
        )
    if now < waiver.issued_at:
        return WaiverCheck(waiver.waiver_id, False, False, False, "The waiver is not active yet.")
    if now >= waiver.expires_at:
        return WaiverCheck(
            waiver.waiver_id,
            False,
            False,
            True,
            "The waiver expired and the normal gate is restored.",
        )
    return WaiverCheck(
        waiver.waiver_id,
        True,
        True,
        False,
        "A human waiver temporarily permits the action; the factual standing state is unchanged.",
    )


@dataclass(frozen=True)
class StandingTimelineEvent:
    """One normalized standing journal event."""

    event_id: str
    decision_id: str
    occurred_at: float
    revision_id: str | None
    state: str | None
    action: str | None
    fingerprint: str | None
    explanation: str | None
    waiver_id: str | None
    event_type: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StandingTimelineEvent:
        if not isinstance(raw, Mapping):
            raise LifecycleError("standing journal event must be a mapping")
        evaluated = raw.get("evaluated")
        acted = raw.get("acted")
        forward = raw.get("forward")
        extra = raw.get("extra")
        if not isinstance(evaluated, Mapping):
            raise LifecycleError("standing journal event evaluated field must be a mapping")
        if not isinstance(acted, Mapping):
            raise LifecycleError("standing journal event acted field must be a mapping")
        if forward is not None and not isinstance(forward, Mapping):
            raise LifecycleError("standing journal event forward field must be a mapping")
        if extra is not None and not isinstance(extra, Mapping):
            raise LifecycleError("standing journal event extra field must be a mapping")
        event_id = _required_string(raw.get("id"), "event id")
        decision_id = _required_string(evaluated.get("decision_id"), "evaluated.decision_id")
        revision_id = _optional_string(
            evaluated.get("revision_id")
            if evaluated.get("revision_id") is not None
            else (forward.get("revision_id") if isinstance(forward, Mapping) else None),
            "revision_id",
        )
        state = _optional_string(evaluated.get("state"), "evaluated.state")
        action = _optional_string(acted.get("action"), "acted.action")
        fingerprint = _optional_string(evaluated.get("fingerprint"), "evaluated.fingerprint")
        explanation = _optional_string(acted.get("explanation"), "acted.explanation")
        waiver_id = _optional_string(
            acted.get("waiver_id")
            if acted.get("waiver_id") is not None
            else (extra.get("waiver_id") if isinstance(extra, Mapping) else None),
            "waiver_id",
        )
        event_type = _optional_string(
            extra.get("event_type") if isinstance(extra, Mapping) else None,
            "event_type",
        )
        if event_type is None and state is not None:
            event_type = "standing_change"
        return cls(
            event_id,
            decision_id,
            _unix_time(raw.get("ts"), "event ts"),
            revision_id,
            state,
            action,
            fingerprint,
            explanation,
            waiver_id,
            event_type,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "occurred_at": self.occurred_at,
            "revision_id": self.revision_id,
            "state": self.state,
            "action": self.action,
            "fingerprint": self.fingerprint,
            "explanation": self.explanation,
            "waiver_id": self.waiver_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class StandingTimeline:
    """Journal events for a decision and its latest event at a chosen time."""

    decision_id: str
    as_of: float | None
    events: tuple[StandingTimelineEvent, ...]
    current: StandingTimelineEvent | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "as_of": self.as_of,
            "current": None if self.current is None else self.current.as_dict(),
            "events": [event.as_dict() for event in self.events],
        }


def project_standing_timeline(
    events: Sequence[Mapping[str, Any]],
    decision_id: str,
    *,
    as_of: int | float | str | None = None,
) -> StandingTimeline:
    """Project the standing journal up to ``as_of`` for one decision."""

    key = _required_string(decision_id, "decision_id")
    cutoff = None if as_of is None else _unix_time(as_of, "as_of")
    normalized = tuple(
        event
        for event in (StandingTimelineEvent.from_mapping(raw) for raw in events)
        if event.decision_id == key and (cutoff is None or event.occurred_at <= cutoff)
    )
    ordered = tuple(sorted(normalized, key=lambda event: (event.occurred_at, event.event_id)))
    standing_events = tuple(event for event in ordered if event.state is not None)
    return StandingTimeline(key, cutoff, ordered, standing_events[-1] if standing_events else None)


@dataclass(frozen=True)
class DecisionSnapshot:
    """The governing revision and standing journal view at one point in time."""

    decision_id: str
    as_of: int | None
    revision: DecisionRevision | None
    standing: StandingTimelineEvent | None
    standing_history: tuple[StandingTimelineEvent, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "as_of": self.as_of,
            "revision": None if self.revision is None else self.revision.as_dict(),
            "standing": None if self.standing is None else self.standing.as_dict(),
            "standing_history": [event.as_dict() for event in self.standing_history],
        }


def decision_at(
    decision_id: str,
    revisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    as_of: int | None = None,
) -> DecisionSnapshot:
    """Answer which revision and journal state governed at ``as_of``."""

    revision_timeline = build_revision_timeline(decision_id, revisions, as_of=as_of)
    standing_timeline = project_standing_timeline(events, decision_id, as_of=as_of)
    return DecisionSnapshot(
        decision_id=_required_string(decision_id, "decision_id"),
        as_of=as_of,
        revision=revision_timeline.active_revision,
        standing=standing_timeline.current,
        standing_history=standing_timeline.events,
    )
