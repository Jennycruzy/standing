"""Memory-backed tools used by the Standing reviewer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from fnmatch import fnmatchcase
from time import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

from .approval import ManualApproval, ManualApprovalError
from .artifacts import ArtifactSnapshot
from .acceptance import (
    AcceptancePolicy,
    AcceptanceResult,
    ObserverHistory,
    ObserverSelectionError,
    apply_observer_outcome,
    check_acceptance as check_acceptance_policy,
    select_observer as choose_observer,
)
from .acp import AcpVerifierClient, VerifierObservation
from .evaluator import StandingEvaluation, StandingState, evaluate_standing
from .lifecycle import (
    DecisionRevision,
    DecisionSnapshot,
    LifecycleError,
    Remediation,
    RemediationStatus,
    RemediationTransition,
    Waiver,
    WaiverCheck,
    build_revision_timeline,
    check_waiver,
    decision_at,
    issue_waiver as issue_lifecycle_waiver,
    transition_remediation as transition_lifecycle_remediation,
)
from .memory import MemoryStore
from .model_review import ConfirmedExtraction, DecisionProposal, ModelReviewError
from .temporal import (
    TemporalEvidence,
    TemporalObservation,
    TemporalObservationError,
    parse_timestamp,
)


class ReviewerToolError(RuntimeError):
    """Raised when a reviewer tool receives an invalid or unsafe request."""


@dataclass(frozen=True)
class DecisionHit:
    """A decision found by one or more governed paths."""

    decision_id: str
    title: str
    governed_paths: tuple[str, ...]


@dataclass(frozen=True)
class DecisionRecord:
    """The stored decision body and its stable identifier."""

    decision_id: str
    body: dict[str, Any]


@dataclass(frozen=True)
class ConditionRecord:
    """The current condition record used by the evaluator."""

    condition_key: str
    body: dict[str, Any]


@dataclass(frozen=True)
class ReviewItem:
    """One decision review and whether the evaluator permits blocking."""

    decision_id: str
    evaluation: StandingEvaluation
    blocks: bool


@dataclass(frozen=True)
class AcceptancePromotion:
    """The durable condition update and dependent decisions it changed."""

    condition_key: str
    condition_reference: dict[str, Any]
    affected_decision_ids: tuple[str, ...]
    standing_change_event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "condition_reference": dict(self.condition_reference),
            "affected_decision_ids": list(self.affected_decision_ids),
            "standing_change_event_ids": list(self.standing_change_event_ids),
        }


@dataclass(frozen=True)
class BootState:
    """The journal records available when a fresh reviewer starts."""

    changes: tuple[dict[str, Any], ...]


class ReviewerTools:
    """Narrow tools that connect memory to the pure evaluator."""

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def search_decisions(self, paths: Sequence[str]) -> tuple[DecisionHit, ...]:
        """Find decisions whose approved governed paths match the changed files."""

        requested_paths = tuple(_normalize_path(path) for path in paths)
        hits: list[DecisionHit] = []
        for result in self.memory.search_decisions(requested_paths):
            decision_id = _required_string(result.get("key"), "decision key")
            body = _body(result, decision_id)
            status = body.get("status")
            if isinstance(status, str) and status.upper() in {"SUPERSEDED", "ARCHIVED"}:
                continue
            title = body.get("title", decision_id)
            if not isinstance(title, str) or not title.strip():
                raise ReviewerToolError(f"decision {decision_id} has no usable title")
            governed_paths = body.get("governed_paths", [])
            if not isinstance(governed_paths, Sequence) or isinstance(governed_paths, (str, bytes)):
                raise ReviewerToolError(f"decision {decision_id} has invalid governed paths")
            normalized_paths: list[str] = []
            for path in governed_paths:
                normalized_paths.append(_normalize_path(path))
            if not any(
                _path_matches(requested, governed)
                for requested in requested_paths
                for governed in normalized_paths
            ):
                # Sibyl search is a candidate finder only.  Never turn a
                # semantic/full-text hit into governance without this exact
                # stored-path validation.
                continue
            hits.append(DecisionHit(decision_id, title.strip(), tuple(normalized_paths)))
        return tuple(sorted(hits, key=lambda hit: hit.decision_id))

    def read_decision(self, decision_id: str) -> DecisionRecord:
        """Read one decision by its stored key."""

        key = _required_string(decision_id, "decision_id")
        return DecisionRecord(key, _body(self.memory.read_decision(key), key))

    def ingest_artifact(self, artifact: ArtifactSnapshot) -> dict[str, Any]:
        """Persist a bounded artifact capture before any model extraction."""

        if not isinstance(artifact, ArtifactSnapshot):
            raise ReviewerToolError("artifact must be an ArtifactSnapshot")
        return self.memory.save_artifact(
            f"artifact:{artifact.sha256}",
            artifact.as_dict(include_text=True),
        )

    def record_decision_proposal(
        self,
        proposal: DecisionProposal | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist an advisory decision proposal without making it govern code."""

        try:
            parsed = proposal if isinstance(proposal, DecisionProposal) else DecisionProposal.from_mapping(proposal)
        except ModelReviewError as error:
            raise ReviewerToolError(str(error)) from error
        stored = self.memory.save_decision_proposal(parsed.proposal_id, parsed.as_dict())
        self.memory.record_lifecycle_event(
            event_type="decision_proposal_recorded",
            decision_id=parsed.decision_id,
            acted={
                "action": "propose",
                "actor_id": parsed.model_id,
                "explanation": "Advisory proposal awaiting explicit human confirmation.",
            },
            forward={"proposal_id": parsed.proposal_id, "status": "PENDING"},
            extra={"artifact_path": parsed.artifact_path, "artifact_sha256": parsed.artifact_sha256},
        )
        return stored

    def confirm_decision_proposal(
        self,
        proposal_id: str,
        *,
        confirmed_by: str,
        confirmation_note: str,
        confirmed_at: int | date | datetime | str | None = None,
    ) -> DecisionRecord:
        """Human-confirm a proposal and only then promote it to a decision."""

        key = _required_string(proposal_id, "proposal_id")
        actor = _required_string(confirmed_by, "confirmed_by")
        if actor.lower() == "model":
            raise ReviewerToolError("a model cannot confirm a decision proposal")
        note = _required_string(confirmation_note, "confirmation_note")
        timestamp = int(time()) if confirmed_at is None else parse_timestamp(confirmed_at, label="confirmed_at")
        try:
            stored = self.memory.read_decision_proposal(key)
        except NotFoundError as error:
            raise ReviewerToolError(f"decision proposal {key} was not found") from error
        try:
            proposal = DecisionProposal.from_mapping(_body(stored, key))
        except ModelReviewError as error:
            raise ReviewerToolError(str(error)) from error
        if proposal.status != "PENDING":
            raise ReviewerToolError(f"decision proposal {key} is already {proposal.status}")
        try:
            self.memory.read_decision(proposal.decision_id)
        except NotFoundError:
            pass
        else:
            raise ReviewerToolError(f"decision {proposal.decision_id} already exists")

        conditions: list[dict[str, Any]] = []
        for raw_condition in proposal.conditions:
            condition = dict(raw_condition)
            condition["provenance"] = "CONFIRMED"
            conditions.append(condition)
        decision_body: dict[str, Any] = {
            "decision_id": proposal.decision_id,
            "title": proposal.title,
            "description": proposal.description,
            "recorded_at": timestamp,
            "effective_from": timestamp,
            "status": "CURRENT",
            "author": proposal.model_id,
            "approver": actor,
            "governed_paths": list(proposal.governed_paths),
            "conditions": conditions,
            "source_artifact": {
                "path": proposal.artifact_path,
                "artifact_type": proposal.artifact_type,
                "sha256": proposal.artifact_sha256,
            },
            "source_sentence": proposal.source_sentence,
            "proposal_id": proposal.proposal_id,
            "confirmation_note": note,
            "confirmed_at": timestamp,
        }
        self.memory.save_decision(proposal.decision_id, decision_body)
        updated_proposal = proposal.as_dict()
        updated_proposal.update(
            {
                "status": "CONFIRMED",
                "confirmed_by": actor,
                "confirmed_at": timestamp,
                "confirmation_note": note,
                "confirmation_id": f"confirmation:{proposal.proposal_id}:{timestamp}",
            }
        )
        self.memory.save_decision_proposal(key, updated_proposal)
        self.memory.record_lifecycle_event(
            event_type="decision_proposal_confirmed",
            decision_id=proposal.decision_id,
            acted={"action": "confirm", "actor_id": actor, "explanation": note},
            forward={
                "proposal_id": proposal.proposal_id,
                "decision_id": proposal.decision_id,
                "confirmed_at": timestamp,
            },
            extra={"source_artifact_sha256": proposal.artifact_sha256},
        )
        return self.read_decision(proposal.decision_id)

    def reject_decision_proposal(
        self,
        proposal_id: str,
        *,
        rejected_by: str,
        reason: str,
        rejected_at: int | date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Reject a proposal through a human-only, journalled action."""

        key = _required_string(proposal_id, "proposal_id")
        actor = _required_string(rejected_by, "rejected_by")
        if actor.lower() == "model":
            raise ReviewerToolError("a model cannot reject a decision proposal")
        explanation = _required_string(reason, "reason")
        timestamp = int(time()) if rejected_at is None else parse_timestamp(rejected_at, label="rejected_at")
        try:
            stored = self.memory.read_decision_proposal(key)
        except NotFoundError as error:
            raise ReviewerToolError(f"decision proposal {key} was not found") from error
        try:
            proposal = DecisionProposal.from_mapping(_body(stored, key))
        except ModelReviewError as error:
            raise ReviewerToolError(str(error)) from error
        if proposal.status != "PENDING":
            raise ReviewerToolError(f"decision proposal {key} is already {proposal.status}")
        updated = proposal.as_dict()
        updated.update(
            {
                "status": "REJECTED",
                "rejected_by": actor,
                "rejected_at": timestamp,
                "rejection_reason": explanation,
            }
        )
        saved = self.memory.save_decision_proposal(key, updated)
        self.memory.record_lifecycle_event(
            event_type="decision_proposal_rejected",
            decision_id=proposal.decision_id,
            acted={"action": "reject", "actor_id": actor, "explanation": explanation},
            forward={"proposal_id": proposal.proposal_id, "rejected_at": timestamp},
            extra={},
        )
        return saved

    def current_decision(self, path: str) -> DecisionRecord | None:
        """Return the active decision that governs one repository path today."""

        return self._decision_for_path(path)

    def decision_as_of(
        self,
        path: str,
        valid_at: int | date | datetime | str,
    ) -> DecisionRecord | None:
        """Return the decision now reconstructed for a historical valid date."""

        timestamp = self._decision_timestamp(valid_at, "valid_at")
        candidates = self._decision_candidates(path)
        eligible: list[tuple[int, int, str, DecisionRecord]] = []
        for record in candidates:
            effective = self._decision_timestamp_or_none(record.body.get("effective_from"), "effective_from")
            if effective is None or effective > timestamp:
                continue
            superseded = self._decision_timestamp_or_none(record.body.get("superseded_at"), "superseded_at")
            if superseded is not None and timestamp >= superseded:
                continue
            eligible.append((effective, self._decision_timestamp_or_none(record.body.get("recorded_at"), "recorded_at") or 0, record.decision_id, record))
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item[0], item[1], item[2]))[3]

    def decision_known_as_of(
        self,
        path: str,
        knowledge_at: int | date | datetime | str,
    ) -> DecisionRecord | None:
        """Return what Standing could have known governed a path then."""

        timestamp = self._decision_timestamp(knowledge_at, "knowledge_at")
        candidates = self._decision_candidates(path)
        eligible: list[tuple[int, int, str, DecisionRecord]] = []
        for record in candidates:
            recorded = self._decision_timestamp_or_none(record.body.get("recorded_at"), "recorded_at")
            effective = self._decision_timestamp_or_none(record.body.get("effective_from"), "effective_from")
            if recorded is None or effective is None or recorded > timestamp or effective > timestamp:
                continue
            superseded = self._decision_timestamp_or_none(record.body.get("superseded_at"), "superseded_at")
            if superseded is not None and timestamp >= superseded:
                # A replacement can become effective before Standing learns
                # about it. Apply the relationship in a knowledge query only
                # after the supersession was recorded. Older rows lack this
                # field, so their effective time is the compatibility fallback.
                supersession_recorded = self._decision_timestamp_or_none(
                    record.body.get("supersession_recorded_at", superseded),
                    "supersession_recorded_at",
                )
                if supersession_recorded is not None and timestamp >= supersession_recorded:
                    continue
            eligible.append((effective, recorded, record.decision_id, record))
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item[0], item[1], item[2]))[3]

    def record_decision_revision(
        self,
        revision: DecisionRevision | Mapping[str, Any],
        *,
        actor_id: str,
        reason: str,
    ) -> DecisionRevision:
        """Persist and promote a validated revision, preserving its predecessor."""

        parsed = revision if isinstance(revision, DecisionRevision) else DecisionRevision.from_mapping(revision)
        actor = _required_string(actor_id, "actor_id")
        explanation = _required_string(reason, "reason")
        existing_rows = self.memory.list_decision_revisions(parsed.decision_id)
        existing = [_body(row, parsed.revision_id) for row in existing_rows]
        try:
            build_revision_timeline(
                parsed.decision_id,
                [*existing, parsed.as_dict()],
            )
        except LifecycleError as error:
            raise ReviewerToolError(str(error)) from error
        self.memory.save_decision_revision(parsed)
        self.memory.save_decision(parsed.decision_id, parsed.materialized_body())
        self.memory.record_lifecycle_event(
            event_type="decision_revision_recorded",
            decision_id=parsed.decision_id,
            acted={
                "action": "supersede" if parsed.supersedes_revision_id is not None else "record",
                "actor_id": actor,
                "explanation": explanation,
            },
            forward={
                "revision_id": parsed.revision_id,
                "supersedes_revision_id": parsed.supersedes_revision_id,
            },
            extra={"revision": parsed.as_dict()},
        )
        return parsed

    def record_replacement_decision(
        self,
        old_decision_id: str,
        new_decision_id: str,
        body: Mapping[str, Any],
        *,
        actor_id: str,
        reason: str,
        effective_from: int | date | datetime | str,
        recorded_at: int | date | datetime | str,
    ) -> DecisionRecord:
        """Record a new decision and explicitly supersede its predecessor."""

        old_key = _required_string(old_decision_id, "old_decision_id")
        new_key = _required_string(new_decision_id, "new_decision_id")
        if old_key == new_key:
            raise ReviewerToolError("replacement decision must have a different ID")
        actor = _required_string(actor_id, "actor_id")
        explanation = _required_string(reason, "reason")
        if actor.lower() == "model":
            raise ReviewerToolError("a model cannot record or approve a replacement decision")
        new_body = dict(body)
        new_body["decision_id"] = new_key
        new_body["status"] = "CURRENT"
        new_body["effective_from"] = parse_timestamp(effective_from, label="effective_from")
        new_body["recorded_at"] = parse_timestamp(recorded_at, label="recorded_at")
        new_body["supersedes"] = old_key
        try:
            old_record = self.read_decision(old_key)
        except NotFoundError as error:
            raise ReviewerToolError(f"decision {old_key} was not found") from error
        if old_record.body.get("status") == "SUPERSEDED":
            raise ReviewerToolError(f"decision {old_key} is already superseded")
        old_effective = self._decision_timestamp_or_none(
            old_record.body.get("effective_from"),
            "effective_from",
        )
        if old_effective is not None and new_body["effective_from"] < old_effective:
            raise ReviewerToolError("replacement decision cannot become effective before its predecessor")
        try:
            self.read_decision(new_key)
        except NotFoundError:
            pass
        else:
            raise ReviewerToolError(f"replacement decision {new_key} already exists")
        self.memory.save_decision(new_key, new_body)

        old_body = old_record.body
        superseded_at = new_body["effective_from"]
        old_body.update(
            {
                "status": "SUPERSEDED",
                "superseded_at": superseded_at,
                "superseded_by": new_key,
                "supersession_reason": explanation,
                "superseded_by_actor": actor,
                "supersession_recorded_at": new_body["recorded_at"],
            }
        )
        self.memory.save_decision(old_key, old_body)
        self.memory.record_lifecycle_event(
            event_type="decision_superseded",
            decision_id=old_key,
            acted={
                "action": "supersede",
                "actor_id": actor,
                "explanation": explanation,
            },
            forward={
                "superseded_by": new_key,
                "superseded_at": superseded_at,
                "supersession_recorded_at": new_body["recorded_at"],
            },
            extra={"replacement_decision": new_body},
        )
        return self.read_decision(new_key)

    def read_decision_at(self, decision_id: str, *, as_of: int | None = None) -> DecisionSnapshot:
        """Read the governing revision and journal state at a historical instant."""

        key = _required_string(decision_id, "decision_id")
        rows = self.memory.list_decision_revisions(key)
        revisions = [_body(row, key) for row in rows]
        try:
            return decision_at(key, revisions, self.memory.read_standing_changes(), as_of=as_of)
        except LifecycleError as error:
            raise ReviewerToolError(str(error)) from error

    def read_condition(self, condition_key: str) -> ConditionRecord:
        """Read the accepted current value for one condition."""

        key = _required_string(condition_key, "condition_key")
        current = self._current_condition(key)
        if current is None:
            raise ReviewerToolError(f"condition {key} has no current value")
        return ConditionRecord(key, current)

    def read_observer(self, address: str) -> dict[str, Any]:
        """Read one observer reliability record from memory."""

        key = _required_string(address, "observer address")
        return self.memory.read_observer(key)

    def record_observation(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        """Persist a legacy-compatible checked observation.

        New integrations should use ``record_temporal_observation`` so an
        incomplete record cannot enter the governed evidence path.
        """

        if not isinstance(observation, Mapping):
            raise ReviewerToolError("observation must be a mapping")
        condition_key = _required_string(observation.get("condition_key"), "condition_key")
        observation_uid = _required_string(observation.get("observation_uid"), "observation_uid")
        body = dict(observation)
        body["condition_key"] = condition_key
        body["observation_uid"] = observation_uid
        return self.memory.save_observation(observation_uid, body)

    def record_temporal_observation(
        self,
        observation: TemporalObservation | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate and persist one complete bitemporal observation."""

        try:
            return self.memory.save_temporal_observation(observation)
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    def record_verifier_observation(
        self,
        observation: VerifierObservation,
        *,
        recorded_at: int | date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Record a verifier delivery with Standing's local knowledge time.

        The seller can report when it observed the source, but only the buyer
        knows when the delivery entered Standing's evidence ledger. Keeping
        that receipt time separate is what makes a late discovery queryable.
        """

        if not isinstance(observation, VerifierObservation):
            raise ReviewerToolError("observation must be a VerifierObservation")
        record = observation.as_acceptance_record()
        observed = record.get("observed_at")
        if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
            raise ReviewerToolError("verifier observation has no valid observed_at")
        receipt = int(time()) if recorded_at is None else parse_timestamp(recorded_at, label="recorded_at")
        record["recorded_at"] = max(receipt, observed)
        record["knowledge_recorded_by"] = "standing:reviewer"
        if _usable_ref_uid(record.get("ref_uid")) is None:
            predecessor = self._predecessor_observation_uid(
                observation.condition_key,
                observation.effective_from,
            )
            if predecessor is not None:
                record["ref_uid"] = predecessor
        stored = self.record_temporal_observation(record)
        self._record_observer_identity(observation)
        return stored

    def record_confirmed_extraction(
        self,
        extraction: ConfirmedExtraction,
        *,
        value_type: str,
        unit: str,
        observed_at: int | date | datetime | str | None = None,
        recorded_at: int | date | datetime | str | None = None,
        source_publication_date: int | date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Persist a human-confirmed model extraction as governed evidence.

        Confirmation records evidence; it does not promote a condition or
        bypass the configured acceptance policy. Callers must still run
        ``check_acceptance`` and explicitly call ``promote_acceptance``.
        """

        if not isinstance(extraction, ConfirmedExtraction):
            raise ReviewerToolError("extraction must be a ConfirmedExtraction")
        type_name = _required_string(value_type, "value_type")
        unit_name = _required_string(unit, "unit")
        observed_timestamp = (
            extraction.confirmed_at
            if observed_at is None
            else parse_timestamp(observed_at, label="observed_at")
        )
        receipt_timestamp = (
            int(time())
            if recorded_at is None
            else parse_timestamp(recorded_at, label="recorded_at")
        )
        if receipt_timestamp < observed_timestamp:
            raise ReviewerToolError("recorded_at must not precede observed_at")
        observation = extraction.as_observation()
        observation.update(
            {
                "value_type": type_name,
                "unit": unit_name,
                "source_domain": urlparse(extraction.proposal.source_url).hostname,
                "attester": extraction.confirmed_by,
                "operator_id": extraction.confirmed_by,
                "observed_at": observed_timestamp,
                "recorded_at": receipt_timestamp,
                "knowledge_recorded_by": "standing:reviewer",
                "extraction_method": "MANUAL_VERIFIED",
                "extraction_version": f"human-confirmed:{extraction.proposal.model_id}",
                "evidence_hash": extraction.source_sha256,
                "source_document_hash": extraction.source_sha256,
                "source_snapshot_hash": extraction.source_sha256,
                "source_publication_date": (
                    None
                    if source_publication_date is None
                    else parse_timestamp(source_publication_date, label="source_publication_date")
                ),
            }
        )
        if _usable_ref_uid(observation.get("ref_uid")) is None:
            predecessor = self._predecessor_observation_uid(
                extraction.proposal.condition_key,
                extraction.proposal.effective_from,
            )
            if predecessor is not None:
                observation["ref_uid"] = predecessor
        stored = self.record_temporal_observation(observation)
        self.memory.record_lifecycle_event(
            event_type="extraction_confirmation_recorded",
            decision_id=f"condition:{extraction.proposal.condition_key}",
            acted={
                "action": "confirm_extraction",
                "actor_id": extraction.confirmed_by,
                "explanation": extraction.review_note,
            },
            forward={
                "observation_uid": extraction.observation_uid,
                "condition_key": extraction.proposal.condition_key,
                "effective_from": extraction.proposal.effective_from,
            },
            extra={
                "confirmation_id": extraction.confirmation_id,
                "confirmation_fingerprint": extraction.confirmation_fingerprint,
                "proposal_fingerprint": extraction.proposal.fingerprint,
                "source_snapshot_hash": extraction.source_sha256,
            },
        )
        return stored

    def open_remediation(
        self,
        remediation_id: str,
        decision_id: str,
        revision_id: str,
        *,
        opened_at: int,
        summary: str,
        actor_id: str,
    ) -> Remediation:
        """Open and journal a remediation for one decision revision."""

        try:
            remediation = Remediation.create(
                remediation_id,
                decision_id,
                revision_id,
                opened_at=opened_at,
                summary=summary,
            )
        except LifecycleError as error:
            raise ReviewerToolError(str(error)) from error
        actor = _required_string(actor_id, "actor_id")
        self.memory.save_remediation(remediation)
        self.memory.record_lifecycle_event(
            event_type="remediation_opened",
            decision_id=remediation.decision_id,
            acted={"action": "open", "actor_id": actor, "explanation": remediation.summary},
            forward=remediation.as_dict(),
        )
        return remediation

    def transition_remediation(
        self,
        remediation_id: str,
        target_status: RemediationStatus | str,
        *,
        occurred_at: int,
        actor_id: str,
        reason: str,
        superseded_by_revision_id: str | None = None,
    ) -> RemediationTransition:
        """Apply, persist, and journal one valid remediation transition."""

        key = _required_string(remediation_id, "remediation_id")
        try:
            current = Remediation.from_mapping(_body(self.memory.read_remediation(key), key))
            transition = transition_lifecycle_remediation(
                current,
                target_status,
                occurred_at=occurred_at,
                actor_id=actor_id,
                reason=reason,
                superseded_by_revision_id=superseded_by_revision_id,
            )
        except LifecycleError as error:
            raise ReviewerToolError(str(error)) from error
        self.memory.save_remediation(transition.remediation)
        self.memory.record_lifecycle_event(
            event_type="remediation_transition",
            decision_id=transition.remediation.decision_id,
            acted={
                "action": "transition",
                "actor_id": transition.actor_id,
                "explanation": transition.reason,
            },
            forward=transition.remediation.as_dict(),
            extra={
                "remediation_id": transition.remediation.remediation_id,
                "from_status": transition.from_status.value,
                "to_status": transition.to_status.value,
            },
        )
        return transition

    def issue_waiver(
        self,
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
        """Persist and journal a human-only, expiring action waiver."""

        try:
            waiver = issue_lifecycle_waiver(
                waiver_id,
                decision_id,
                condition_key=condition_key,
                reason=reason,
                issued_by=issued_by,
                issuer_role=issuer_role,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except LifecycleError as error:
            raise ReviewerToolError(str(error)) from error
        self.memory.save_waiver(waiver)
        self.memory.record_lifecycle_event(
            event_type="waiver_issued",
            decision_id=waiver.decision_id,
            acted={
                "action": "waive",
                "actor_id": waiver.issued_by,
                "explanation": waiver.reason,
                "waiver_id": waiver.waiver_id,
            },
            forward=waiver.as_dict(),
        )
        return waiver

    def record_manual_approval(
        self,
        approval: ManualApproval | Mapping[str, Any],
    ) -> ManualApproval:
        """Persist and journal an evidence-bound human approval."""

        try:
            parsed = approval if isinstance(approval, ManualApproval) else ManualApproval.from_mapping(approval)
        except ManualApprovalError as error:
            raise ReviewerToolError(str(error)) from error
        self.memory.save_manual_approval(parsed)
        self.memory.record_lifecycle_event(
            event_type="manual_approval_recorded",
            decision_id=f"condition:{parsed.condition_key}",
            acted={
                "action": "approve",
                "actor_id": parsed.approved_by,
                "explanation": parsed.reason,
                "approval_id": parsed.approval_id,
            },
            forward=parsed.as_dict(),
            extra={"condition_key": parsed.condition_key},
        )
        return parsed

    def read_observations(self, condition_key: str) -> tuple[dict[str, Any], ...]:
        """Read all checked observations for one condition."""

        key = _required_string(condition_key, "condition_key")
        return tuple(self.memory.list_observations(key))

    def current_condition(
        self,
        condition_key: str,
        *,
        as_of: int | date | datetime | str | None = None,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Resolve the canonical current observation for a condition."""

        key = _required_string(condition_key, "condition_key")
        try:
            return self.memory.current_observation(
                key,
                as_of=as_of,
                accepted_only=accepted_only,
            )
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    def condition_valid_as_of(
        self,
        condition_key: str,
        valid_at: int | date | datetime | str,
        *,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Resolve what is now believed to have been true at a valid date."""

        key = _required_string(condition_key, "condition_key")
        try:
            return self.memory.valid_observation_as_of(
                key,
                valid_at,
                accepted_only=accepted_only,
            )
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    def condition_known_as_of(
        self,
        condition_key: str,
        knowledge_at: int | date | datetime | str,
        *,
        valid_at: int | date | datetime | str | None = None,
        accepted_only: bool = True,
    ) -> TemporalObservation | None:
        """Resolve the fact Standing could have known at a knowledge date."""

        key = _required_string(condition_key, "condition_key")
        try:
            return self.memory.known_observation_as_of(
                key,
                knowledge_at,
                valid_at=valid_at,
                accepted_only=accepted_only,
            )
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    def condition_history(
        self,
        condition_key: str,
        *,
        knowledge_at: int | date | datetime | str | None = None,
        accepted_only: bool = False,
    ) -> tuple[TemporalObservation, ...]:
        """Read the full bitemporal history without collapsing supersession."""

        key = _required_string(condition_key, "condition_key")
        try:
            return self.memory.observation_history(
                key,
                knowledge_at=knowledge_at,
                accepted_only=accepted_only,
            )
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    def select_observer(
        self,
        addresses: Sequence[str],
        policy: AcceptancePolicy,
    ) -> ObserverHistory:
        """Choose an observer from the reliability records in memory."""

        histories: list[ObserverHistory] = []
        for address in sorted({_required_string(item, "observer address") for item in addresses}):
            try:
                entity = self.memory.read_observer(address)
            except NotFoundError:
                continue
            histories.append(ObserverHistory.from_mapping(address, _body(entity, address)))
        try:
            return choose_observer(histories, policy)
        except ObserverSelectionError as error:
            raise ReviewerToolError(str(error)) from error

    def check_acceptance(
        self,
        condition_key: str,
        observations: Sequence[Mapping[str, Any]],
        *,
        manual_approval: bool,
        manual_approval_record: Mapping[str, Any] | None = None,
        policy: AcceptancePolicy,
        source_binding: Mapping[str, Any] | None = None,
        now_unix: int | None = None,
    ) -> AcceptanceResult:
        """Apply the policy using observer records read from memory."""

        key = _required_string(condition_key, "condition_key")
        addresses: set[str] = set()
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise ReviewerToolError("each observation must be a mapping")
            address = observation.get("observer_address")
            if address is not None:
                addresses.add(_required_string(address, "observer address"))

        observer_records: dict[str, Mapping[str, Any]] = {}
        for address in sorted(addresses):
            try:
                entity = self.memory.read_observer(address)
            except NotFoundError:
                continue
            observer_records[address] = _body(entity, address)
        return check_acceptance_policy(
            key,
            observations,
            observer_records,
            manual_approval=manual_approval,
            manual_approval_record=manual_approval_record,
            policy=policy,
            source_binding=source_binding,
            now_unix=now_unix,
        )

    def promote_acceptance(
        self,
        condition_key: str,
        result: AcceptanceResult,
        observations: Sequence[Mapping[str, Any]],
        *,
        accepted_at: int | date | datetime | str | None = None,
        basis: str = "accepted by the configured evidence policy",
        max_age_seconds: int | None = None,
        recheck_interval_seconds: int | None = None,
    ) -> AcceptancePromotion:
        """Persist an accepted canonical head and re-evaluate its dependents.

        The method is deliberately downstream of ``check_acceptance``.  It
        refuses contested results and uses the temporal resolver for complete
        observation sets, so an older value cannot be promoted merely because
        it arrived later.
        """

        key = _required_string(condition_key, "condition_key")
        if result.condition_key != key:
            raise ReviewerToolError("condition_key does not match the acceptance result")
        if not result.accepted:
            raise ReviewerToolError("only an accepted result can be promoted")
        explanation = _required_string(basis, "basis")
        accepted_timestamp = int(time()) if accepted_at is None else parse_timestamp(accepted_at, label="accepted_at")

        chosen: TemporalObservation | None = None
        temporal = TemporalEvidence.from_mappings(
            observations,
            strict=False,
            condition_key=key,
        )
        if temporal.is_bitemporal:
            try:
                resolution = temporal.resolve(valid_at=accepted_timestamp, accepted_only=False)
            except TemporalObservationError as error:
                raise ReviewerToolError(str(error)) from error
            if resolution.conflict:
                raise ReviewerToolError("a contested temporal head cannot be promoted")
            chosen = resolution.current
            if chosen is None:
                raise ReviewerToolError("no canonical temporal observation can be promoted")

        # Keep the acceptance decision attached to the immutable evidence
        # rows as well as in the evaluator-facing condition reference.  This
        # makes ``accepted_only`` queries auditable and prevents an
        # unreviewed row from becoming eligible merely because it shares a
        # condition key with an accepted row.
        accepted_uids = set(result.observation_uids)
        for raw_observation in observations:
            uid = raw_observation.get("observation_uid")
            if not isinstance(uid, str) or uid not in accepted_uids:
                continue
            updated_observation = dict(raw_observation)
            updated_observation["accepted"] = True
            try:
                self.memory.save_observation(uid, updated_observation)
            except (TypeError, ValueError) as error:
                raise ReviewerToolError(
                    f"accepted observation {uid} could not be persisted"
                ) from error

        reference = _accepted_condition_reference(
            key,
            result,
            observations,
            chosen=chosen,
            accepted_at=accepted_timestamp,
            basis=explanation,
            max_age_seconds=max_age_seconds,
            recheck_interval_seconds=recheck_interval_seconds,
        )
        self.memory.save_condition_reference(
            key,
            reference,
            metadata={
                "condition_key": key,
                "accepted_at": accepted_timestamp,
                "observation_uids": reference["observation_uids"],
                "temporal": chosen is not None,
            },
        )

        affected: list[str] = []
        standing_events: list[str] = []
        for entity in self.memory.list_decisions():
            decision_id = entity.get("key", entity.get("name"))
            if not isinstance(decision_id, str) or not decision_id.strip():
                raise ReviewerToolError("Sibyl returned a decision without an identifier")
            body = _body(entity, decision_id)
            if not _decision_depends_on(body, key):
                continue
            affected.append(decision_id)
            evaluation = self.evaluate_standing(decision_id)
            action = (
                "block"
                if evaluation.state != StandingState.STANDS
                and any(condition.blocks for condition in evaluation.conditions)
                else "allow"
            )
            existing = self.memory.read_standing(decision_id)
            if (
                existing is not None
                and existing.get("fingerprint") == evaluation.fingerprint
                and existing.get("action") == action
            ):
                continue
            standing_events.append(
                self.write_standing_change(
                    decision_id,
                    evaluation,
                    action=action,
                    explanation=f"Condition {key} acceptance was promoted and dependents were re-evaluated.",
                    now_unix=accepted_timestamp,
                )
            )

        self.memory.record_lifecycle_event(
            event_type="condition_acceptance_promoted",
            decision_id=f"condition:{key}",
            acted={
                "action": "promote_acceptance",
                "actor_id": "standing:acceptance-policy",
                "explanation": explanation,
            },
            forward=reference,
            extra={
                "affected_decision_ids": affected,
                "standing_change_event_ids": standing_events,
            },
        )
        return AcceptancePromotion(
            condition_key=key,
            condition_reference=reference,
            affected_decision_ids=tuple(affected),
            standing_change_event_ids=tuple(standing_events),
        )

    def mark_condition_stale(
        self,
        condition_key: str,
        *,
        stale_observation_uids: Sequence[str] = (),
        reason: str = "condition evidence requires fresh verification",
    ) -> None:
        """Persist an explicit unsafe marker until fresh evidence is promoted."""

        key = _required_string(condition_key, "condition_key")
        explanation = _required_string(reason, "reason")
        reference = self.memory.read_condition_reference(key)
        if reference is None:
            return
        body = reference.get("body")
        if not isinstance(body, dict):
            raise ReviewerToolError(f"condition reference {key} has an invalid body")
        updated = dict(body)
        updated["evidence_fresh"] = False
        updated["freshness_status"] = "STALE"
        updated["freshness_reason"] = explanation
        updated["stale_observation_uids"] = sorted(
            {_required_string(uid, "stale observation UID") for uid in stale_observation_uids}
        )
        self.memory.save_condition_reference(
            key,
            updated,
            metadata=reference.get("metadata") if isinstance(reference.get("metadata"), dict) else None,
        )
        self.memory.record_lifecycle_event(
            event_type="condition_marked_stale",
            decision_id=f"condition:{key}",
            acted={
                "action": "mark_stale",
                "actor_id": "standing:freshness-policy",
                "explanation": explanation,
            },
            forward={
                "condition_key": key,
                "stale_observation_uids": updated["stale_observation_uids"],
            },
        )

    def review_paths_with_revalidation(
        self,
        paths: Sequence[str],
        *,
        client: AcpVerifierClient,
        policy: AcceptancePolicy,
        observer_address: str,
        source_specs: Mapping[str, Mapping[str, Any]],
        source_bindings: Mapping[str, Mapping[str, Any]] | None = None,
        manual_approval_records: Mapping[str, Mapping[str, Any]] | None = None,
        spent_today_usdc: float = 0.0,
        now_unix: int | None = None,
    ) -> tuple[ReviewItem, ...]:
        """Revalidate stale dependencies through ACP, then review the paths.

        This is the side-effecting counterpart to ``review_paths``.  Callers
        must explicitly provide an ACP client and its spend context; the
        normal read-only review remains deterministic and network-free.
        """

        current_time = int(time()) if now_unix is None else now_unix
        if isinstance(current_time, bool) or not isinstance(current_time, int) or current_time < 0:
            raise ReviewerToolError("now_unix must be a non-negative integer")
        bindings = {} if source_bindings is None else source_bindings
        approvals = {} if manual_approval_records is None else manual_approval_records
        revalidated: set[str] = set()
        for hit in self.search_decisions(paths):
            decision = self.read_decision(hit.decision_id).body
            raw_conditions = decision.get("conditions")
            if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
                continue
            for raw_condition in raw_conditions:
                if not isinstance(raw_condition, Mapping):
                    continue
                key = _required_string(raw_condition.get("condition_key"), "condition_key")
                if key in revalidated:
                    continue
                observations = self.read_observations(key)
                approval_record = approvals.get(key)
                acceptance = self.check_acceptance(
                    key,
                    observations,
                    manual_approval=approval_record is not None,
                    manual_approval_record=approval_record,
                    policy=policy,
                    source_binding=bindings.get(key),
                    now_unix=current_time,
                )
                needs_revalidation = not observations or bool(acceptance.stale_observation_uids)
                if not needs_revalidation:
                    revalidated.add(key)
                    continue
                self.mark_condition_stale(
                    key,
                    stale_observation_uids=acceptance.stale_observation_uids,
                )
                source_spec = source_specs.get(key)
                if source_spec is None:
                    raise ReviewerToolError(f"no ACP source specification is configured for {key}")
                source_url = _required_string(source_spec.get("source_url"), "source_url")
                value_type = _required_string(source_spec.get("value_type"), "value_type")
                unit = _required_string(source_spec.get("unit"), "unit")
                observation = self.hire_verifier(
                    client,
                    key,
                    observer_address,
                    acceptance=acceptance,
                    spent_today_usdc=spent_today_usdc,
                    source_url=source_url,
                    value_type=value_type,
                    unit=unit,
                )
                self.record_verifier_observation(observation)
                accumulated = self.read_observations(key)
                final_acceptance = self.check_acceptance(
                    key,
                    accumulated,
                    manual_approval=approval_record is not None,
                    manual_approval_record=approval_record,
                    policy=policy,
                    source_binding=bindings.get(key),
                    now_unix=current_time,
                )
                if final_acceptance.accepted:
                    self.promote_acceptance(
                        key,
                        final_acceptance,
                        accumulated,
                        accepted_at=current_time,
                        max_age_seconds=policy.max_observation_age_seconds,
                        recheck_interval_seconds=policy.recheck_interval_seconds,
                    )
                revalidated.add(key)
        return self.review_paths(paths)

    def hire_verifier(
        self,
        client: AcpVerifierClient,
        condition_key: str,
        observer_address: str,
        *,
        acceptance: AcceptanceResult,
        spent_today_usdc: float,
        source_url: str | None = None,
        value_type: str | None = None,
        unit: str | None = None,
        job_id: str | None = None,
        start_verifier: bool | None = None,
        offering_name: str | None = None,
        ref_uid: str | None = None,
    ) -> VerifierObservation:
        """Hire the selected observer through ACP after policy failure."""

        return client.hire_verifier(
            condition_key,
            observer_address,
            acceptance=acceptance,
            spent_today_usdc=spent_today_usdc,
            source_url=source_url,
            value_type=value_type,
            unit=unit,
            job_id=job_id,
            start_verifier=start_verifier,
            offering_name=offering_name,
            ref_uid=ref_uid,
        )

    def record_observer_outcome(self, address: str, *, confirmed: bool) -> ObserverHistory:
        """Update the local observer record after a checked reading."""

        key = _required_string(address, "observer address")
        if not isinstance(confirmed, bool):
            raise ReviewerToolError("confirmed must be true or false")
        entity = self.memory.read_observer(key)
        body = _body(entity, key)
        current = ObserverHistory.from_mapping(key, body)
        updated = apply_observer_outcome(current, confirmed=confirmed)
        body.update(updated.as_counts())
        self.memory.save_observer(key, body)
        return updated

    def _record_observer_identity(self, observation: VerifierObservation) -> None:
        """Persist identity dimensions alongside a verifier's counters.

        Counters are updated only by the explicit outcome call. Recording a
        delivery may therefore create a zero-count observer entity, but it
        still leaves the wallet, operator, source domain, and extraction path
        inspectable before a reliability decision is made.
        """

        address = _required_string(observation.observer_address, "observer address")
        try:
            existing = self.memory.read_observer(address)
            body = _body(existing, address)
        except NotFoundError:
            body = {
                "readings_given": 0,
                "readings_confirmed": 0,
                "readings_contradicted": 0,
            }
        history = ObserverHistory.from_mapping(address, body)
        source_domain = urlparse(observation.source_url).hostname
        domains = set(history.source_domains)
        if source_domain is not None:
            domains.add(source_domain.lower().rstrip("."))
        methods = set(history.extraction_methods)
        if observation.extraction_method is not None:
            methods.add(observation.extraction_method)
        versions = set(history.extraction_versions)
        if observation.extraction_version is not None:
            versions.add(observation.extraction_version)
        body.update(
            {
                "wallet_address": history.wallet_address or address,
                "operator_id": history.operator_id or observation.provenance.operator_id,
                "operator_type": history.operator_type or observation.provenance.operator_type,
                "source_domains": sorted(domains),
                "extraction_methods": sorted(methods),
                "extraction_versions": sorted(versions),
            }
        )
        self.memory.save_observer(address, body)

    def evaluate_standing(self, decision_id: str) -> StandingEvaluation:
        """Read one decision and its current conditions, then evaluate it."""

        decision = self.read_decision(decision_id)
        raw_specs = decision.body.get("conditions")
        if not isinstance(raw_specs, Sequence) or isinstance(raw_specs, (str, bytes)):
            raise ReviewerToolError(f"decision {decision.decision_id} has no condition list")

        current: dict[str, Mapping[str, Any]] = {}
        for raw_spec in raw_specs:
            if not isinstance(raw_spec, Mapping):
                raise ReviewerToolError(f"decision {decision.decision_id} has an invalid condition")
            condition_key = _required_string(raw_spec.get("condition_key"), "condition_key")
            condition = self._current_condition(condition_key)
            if condition is not None:
                current[condition_key] = condition

        evaluator_input = dict(decision.body)
        evaluator_input["decision_id"] = decision.decision_id
        return evaluate_standing(evaluator_input, current)

    def review_paths(self, paths: Sequence[str]) -> tuple[ReviewItem, ...]:
        """Review every remembered decision governing the supplied paths."""

        reviews: list[ReviewItem] = []
        for hit in self.search_decisions(paths):
            evaluation = self.evaluate_standing(hit.decision_id)
            blocks = evaluation.state != StandingState.STANDS and any(
                condition.blocks for condition in evaluation.conditions
            )
            reviews.append(ReviewItem(hit.decision_id, evaluation, blocks))
        return tuple(reviews)

    def write_standing_change(
        self,
        decision_id: str,
        evaluation: StandingEvaluation,
        *,
        action: str,
        explanation: str,
        waiver_id: str | None = None,
        now_unix: int | None = None,
    ) -> str:
        """Write a checked result and reject actions that contradict it."""

        key = _required_string(decision_id, "decision_id")
        if key != evaluation.decision_id:
            raise ReviewerToolError("decision_id does not match the evaluation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ReviewerToolError("explanation must not be empty")
        if action not in {"allow", "block", "note"}:
            raise ReviewerToolError("action must be allow, block, or note")
        if evaluation.state == StandingState.STANDS and action == "block":
            raise ReviewerToolError("a standing decision cannot be blocked by the reviewer")
        waiver_check: WaiverCheck | None = None
        if waiver_id is not None:
            waiver_key = _required_string(waiver_id, "waiver_id")
            if action != "allow":
                raise ReviewerToolError("a waiver can only accompany an allow action")
            if now_unix is None:
                raise ReviewerToolError("now_unix is required when checking a waiver")
            try:
                waiver = Waiver.from_mapping(_body(self.memory.read_waiver(waiver_key), waiver_key))
                waiver_check = check_waiver(
                    waiver,
                    decision_id=key,
                    blocking_condition_keys=tuple(
                        condition.condition_key for condition in evaluation.conditions if condition.blocks
                    ),
                    now_unix=now_unix,
                )
            except LifecycleError as error:
                raise ReviewerToolError(str(error)) from error
            if not waiver_check.permits_action:
                raise ReviewerToolError(waiver_check.reason)
        if evaluation.state != StandingState.STANDS and action != "block":
            if waiver_check is None or not waiver_check.permits_action:
                raise ReviewerToolError("a non-standing decision must be blocked unless a human waiver is active")

        state_body = evaluation.as_dict()
        state_body["action"] = action
        state_body["explanation"] = explanation.strip()
        if waiver_check is not None:
            state_body["waiver"] = waiver_check.as_dict()
        self.memory.save_standing(key, state_body)
        evaluated: dict[str, Any] = {
            "decision_id": key,
            "state": evaluation.state.value,
            "fingerprint": evaluation.fingerprint,
        }
        forward: dict[str, Any] = {"state": evaluation.state.value}
        decision_body = self.read_decision(key).body
        revision_id = decision_body.get("revision_id")
        if isinstance(revision_id, str) and revision_id.strip():
            evaluated["revision_id"] = revision_id.strip()
            forward["revision_id"] = revision_id.strip()
        acted: dict[str, Any] = {"action": action, "explanation": explanation.strip()}
        extra: dict[str, Any] = {
            "condition_states": [condition.state.value for condition in evaluation.conditions]
        }
        if waiver_check is not None:
            acted["waiver_id"] = waiver_check.waiver_id
            extra["waiver"] = waiver_check.as_dict()
        return self.memory.record_standing_change(
            evaluated=evaluated,
            acted=acted,
            forward=forward,
            extra=extra,
        )

    def read_boot_state(self) -> BootState:
        """Read the standing-change journal before a human sends new input."""

        changes = self.memory.read_standing_changes()
        return BootState(tuple(changes))

    def _decision_for_path(self, path: str) -> DecisionRecord | None:
        normalized = _normalize_path(path)
        now = int(time())
        candidates: list[tuple[int, int, str, DecisionRecord]] = []
        for record in self._decision_candidates(normalized):
            status = record.body.get("status")
            if isinstance(status, str) and status.upper() in {"SUPERSEDED", "ARCHIVED"}:
                superseded = self._decision_timestamp_or_none(record.body.get("superseded_at"), "superseded_at")
                if superseded is None or now >= superseded:
                    continue
            superseded = self._decision_timestamp_or_none(record.body.get("superseded_at"), "superseded_at")
            if superseded is not None and now >= superseded:
                continue
            effective = self._decision_timestamp_or_none(record.body.get("effective_from"), "effective_from") or 0
            recorded = self._decision_timestamp_or_none(record.body.get("recorded_at"), "recorded_at") or 0
            if effective > now or recorded > now:
                continue
            candidates.append((effective, recorded, record.decision_id, record))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]

    def _decision_candidates(self, path: str) -> tuple[DecisionRecord, ...]:
        normalized = _normalize_path(path)
        records: list[DecisionRecord] = []
        for entity in self.memory.list_decisions():
            decision_id = entity.get("key", entity.get("name"))
            if not isinstance(decision_id, str) or not decision_id.strip():
                raise ReviewerToolError("Sibyl returned a decision without an identifier")
            body = _body(entity, decision_id)
            governed_paths = body.get("governed_paths", [])
            if not isinstance(governed_paths, Sequence) or isinstance(governed_paths, (str, bytes)):
                raise ReviewerToolError(f"decision {decision_id} has invalid governed paths")
            if any(_path_matches(normalized, _normalize_path(item)) for item in governed_paths):
                records.append(DecisionRecord(decision_id, body))
        return tuple(sorted(records, key=lambda item: item.decision_id))

    @staticmethod
    def _decision_timestamp(value: int | date | datetime | str, label: str) -> int:
        try:
            return parse_timestamp(value, label=label)
        except TemporalObservationError as error:
            raise ReviewerToolError(str(error)) from error

    @staticmethod
    def _decision_timestamp_or_none(value: Any, label: str) -> int | None:
        if value is None:
            return None
        return ReviewerTools._decision_timestamp(value, label)

    def _current_condition(self, condition_key: str) -> dict[str, Any] | None:
        reference = self.memory.read_condition_reference(condition_key)
        if reference is not None:
            body = reference.get("body")
            if not isinstance(body, dict):
                raise ReviewerToolError(f"condition reference {condition_key} has an invalid body")
            merged = dict(body)
            metadata = reference.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ReviewerToolError(f"condition reference {condition_key} has invalid metadata")
            _promote_reference_fields(merged, metadata)
            _apply_condition_freshness(merged)
            return merged

        try:
            entity = self.memory.read_condition(condition_key)
        except NotFoundError:
            return None
        return _body(entity, condition_key)

    def current_condition_reference(self, condition_key: str) -> dict[str, Any] | None:
        """Return the evaluator-facing current condition reference.

        Dashboard and reporting surfaces use this read-only view so they do
        not need to reach into the reviewer implementation.  Freshness is
        applied exactly as it is during standing evaluation.
        """

        key = _required_string(condition_key, "condition_key")
        return self._current_condition(key)

    def _predecessor_observation_uid(
        self,
        condition_key: str,
        effective_from: int,
    ) -> str | None:
        """Find a canonical earlier observation for local supersession lineage.

        The verifier may not know the predecessor before it fetches a source,
        and a late historical reading must not be linked as if it replaced a
        newer fact. This helper only links a new effective period to the
        canonical observation immediately before that period; same-period
        readings remain unlinked so the temporal resolver can report a real
        conflict.
        """

        try:
            existing = self.read_observations(condition_key)
            if not existing:
                return None
            evidence = TemporalEvidence.from_mappings(
                existing,
                strict=True,
                condition_key=condition_key,
            )
            if not evidence.is_complete:
                return None
            resolution = evidence.resolve(
                valid_at=max(0, effective_from - 1),
                accepted_only=False,
            )
        except (ReviewerToolError, TemporalObservationError, ValueError):
            # Legacy rows and an already contested/incomplete ledger are not
            # safe inputs for automatic lineage inference.
            return None
        predecessor = resolution.current
        if predecessor is None or predecessor.effective_from is None:
            return None
        if predecessor.effective_from >= effective_from:
            return None
        return predecessor.observation_uid


def _body(entity: Mapping[str, Any], identifier: str) -> dict[str, Any]:
    body = entity.get("body")
    if not isinstance(body, dict):
        raise ReviewerToolError(f"record {identifier} has no mapping body")
    return dict(body)


def _promote_reference_fields(body: dict[str, Any], metadata: dict[str, Any] | None) -> None:
    if "accepted_value" not in body and "value" in body:
        body["accepted_value"] = body["value"]
    if "accepted_source_url" not in body and "source_url" in body:
        body["accepted_source_url"] = body["source_url"]
    if metadata is None:
        return
    if "observation_uids" not in body and isinstance(metadata.get("observation_uid"), str):
        body["observation_uids"] = [metadata["observation_uid"]]
    if "accepted_source_url" not in body and isinstance(metadata.get("source_url"), str):
        body["accepted_source_url"] = metadata["source_url"]


def _accepted_condition_reference(
    condition_key: str,
    result: AcceptanceResult,
    observations: Sequence[Mapping[str, Any]],
    *,
    chosen: TemporalObservation | None,
    accepted_at: int,
    basis: str,
    max_age_seconds: int | None,
    recheck_interval_seconds: int | None,
) -> dict[str, Any]:
    """Build the evaluator-facing reference from the accepted evidence."""

    if result.accepted_value is None:
        raise ReviewerToolError("an accepted result must contain a value")
    for label, value in (
        ("max_age_seconds", max_age_seconds),
        ("recheck_interval_seconds", recheck_interval_seconds),
    ):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            raise ReviewerToolError(f"{label} must be a positive integer when supplied")
    if chosen is not None:
        chosen_body = chosen.as_dict()
        observation_uids = list(result.canonical_observation_uids) or [chosen.observation_uid]
        reference: dict[str, Any] = {
            "condition_key": condition_key,
            "accepted_value": result.accepted_value,
            "value_type": chosen.value_type,
            "unit": chosen.unit,
            "effective_from": chosen.effective_from,
            "effective_until": chosen.effective_until,
            "accepted_at": accepted_at,
            "accepted_source_url": chosen.source_url,
            "source_domain": chosen.source_domain,
            "source_type": chosen.source_type,
            "observation_uids": observation_uids,
            "basis": basis,
            "status": "ACCEPTED",
            "observed_at": chosen.observed_at,
            "recorded_at": chosen.recorded_at,
            "evidence_hash": chosen.evidence_hash,
            "ref_uid": chosen.ref_uid,
            "controlled_scenario": chosen.controlled_scenario,
            "last_verified_at": accepted_at,
            "evidence_fresh": True,
        }
        if max_age_seconds is not None:
            reference["max_age_seconds"] = max_age_seconds
        if recheck_interval_seconds is not None:
            reference["recheck_interval_seconds"] = recheck_interval_seconds
            reference["next_check_at"] = accepted_at + recheck_interval_seconds
        if "source_snapshot_hash" in chosen_body:
            reference["source_snapshot_hash"] = chosen_body["source_snapshot_hash"]
        return reference

    if not observations:
        raise ReviewerToolError("an accepted result cannot be promoted without observations")
    first = observations[0]
    observation_uids = list(result.observation_uids)
    if not observation_uids:
        uid = first.get("observation_uid")
        if isinstance(uid, str) and uid.strip():
            observation_uids = [uid.strip()]
    reference = {
        "condition_key": condition_key,
        "accepted_value": result.accepted_value,
        "value_type": first.get("value_type"),
        "unit": first.get("unit"),
        "effective_from": first.get("effective_from"),
        "accepted_at": accepted_at,
        "accepted_source_url": first.get("source_url"),
        "source_domain": first.get("source_domain"),
        "source_type": first.get("source_type"),
        "observation_uids": observation_uids,
        "basis": basis,
        "status": "ACCEPTED",
        "temporal": False,
        "last_verified_at": accepted_at,
        "evidence_fresh": True,
    }
    if max_age_seconds is not None:
        reference["max_age_seconds"] = max_age_seconds
    if recheck_interval_seconds is not None:
        reference["recheck_interval_seconds"] = recheck_interval_seconds
        reference["next_check_at"] = accepted_at + recheck_interval_seconds
    return reference


def _decision_depends_on(decision: Mapping[str, Any], condition_key: str) -> bool:
    status = decision.get("status")
    if isinstance(status, str) and status.upper() in {"SUPERSEDED", "ARCHIVED"}:
        return False
    raw_conditions = decision.get("conditions")
    if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
        return False
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, Mapping):
            continue
        if raw_condition.get("condition_key") == condition_key:
            return True
    return False


def _apply_condition_freshness(body: dict[str, Any]) -> None:
    """Derive a current stale marker from a persisted verification timestamp."""

    last_verified = body.get("last_verified_at", body.get("recorded_at"))
    max_age = body.get("max_age_seconds")
    next_check = body.get("next_check_at")
    if last_verified is None and max_age is not None:
        body["evidence_fresh"] = False
        body["freshness_status"] = "STALE"
        body["freshness_reason"] = "last_verified_at is missing"
        return
    last_timestamp: int | None = None
    if last_verified is not None:
        try:
            last_timestamp = parse_timestamp(last_verified, label="last_verified_at")
        except TemporalObservationError:
            body["evidence_fresh"] = False
            body["freshness_status"] = "STALE"
            body["freshness_reason"] = "last_verified_at is invalid"
            return
    if max_age is not None and (
        not isinstance(max_age, int) or isinstance(max_age, bool) or max_age <= 0
    ):
        body["evidence_fresh"] = False
        body["freshness_status"] = "STALE"
        body["freshness_reason"] = "max_age_seconds is invalid"
        return
    now = int(time())
    if max_age is not None and last_timestamp is not None and now - last_timestamp > max_age:
        body["evidence_fresh"] = False
        body["freshness_status"] = "STALE"
        body["freshness_reason"] = "verification age exceeds max_age_seconds"
        return
    if next_check is not None:
        try:
            next_check_timestamp = parse_timestamp(next_check, label="next_check_at")
        except TemporalObservationError:
            body["evidence_fresh"] = False
            body["freshness_status"] = "STALE"
            body["freshness_reason"] = "next_check_at is invalid"
            return
        if now >= next_check_timestamp:
            body["evidence_fresh"] = False
            body["freshness_status"] = "STALE"
            body["freshness_reason"] = "scheduled recheck is due"


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewerToolError(f"{label} must be a non-empty string")
    return value.strip()


def _usable_ref_uid(value: Any) -> str | None:
    """Treat EAS's zero refUID as the absence of a predecessor."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.lower() == "0x" + "0" * 64:
        return None
    return normalized


def _normalize_path(value: Any) -> str:
    path = _required_string(value, "governed path")
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _path_matches(requested: str, governed: str) -> bool:
    """Match a changed repository path against an approved exact/glob path."""

    return requested == governed or fnmatchcase(requested, governed)
