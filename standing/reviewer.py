"""Memory-backed tools used by the Standing reviewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

from .approval import ManualApproval, ManualApprovalError
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
class BootState:
    """The journal records available when a fresh reviewer starts."""

    changes: tuple[dict[str, Any], ...]


class ReviewerTools:
    """Narrow tools that connect memory to the pure evaluator."""

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def search_decisions(self, paths: Sequence[str]) -> tuple[DecisionHit, ...]:
        """Find decisions whose approved governed paths match the changed files."""

        hits: list[DecisionHit] = []
        for result in self.memory.search_decisions(paths):
            decision_id = _required_string(result.get("key"), "decision key")
            body = _body(result, decision_id)
            title = body.get("title", decision_id)
            if not isinstance(title, str) or not title.strip():
                raise ReviewerToolError(f"decision {decision_id} has no usable title")
            governed_paths = body.get("governed_paths", [])
            if not isinstance(governed_paths, Sequence) or isinstance(governed_paths, (str, bytes)):
                raise ReviewerToolError(f"decision {decision_id} has invalid governed paths")
            normalized_paths: list[str] = []
            for path in governed_paths:
                normalized_paths.append(_required_string(path, "governed path"))
            hits.append(DecisionHit(decision_id, title.strip(), tuple(normalized_paths)))
        return tuple(sorted(hits, key=lambda hit: hit.decision_id))

    def read_decision(self, decision_id: str) -> DecisionRecord:
        """Read one decision by its stored key."""

        key = _required_string(decision_id, "decision_id")
        return DecisionRecord(key, _body(self.memory.read_decision(key), key))

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
        """Persist one checked observation for later acceptance evaluations."""

        if not isinstance(observation, Mapping):
            raise ReviewerToolError("observation must be a mapping")
        condition_key = _required_string(observation.get("condition_key"), "condition_key")
        observation_uid = _required_string(observation.get("observation_uid"), "observation_uid")
        body = dict(observation)
        body["condition_key"] = condition_key
        body["observation_uid"] = observation_uid
        return self.memory.save_observation(observation_uid, body)

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
        job_id: str | None = None,
        start_verifier: bool | None = None,
        offering_name: str | None = None,
    ) -> VerifierObservation:
        """Hire the selected observer through ACP after policy failure."""

        return client.hire_verifier(
            condition_key,
            observer_address,
            acceptance=acceptance,
            spent_today_usdc=spent_today_usdc,
            source_url=source_url,
            value_type=value_type,
            job_id=job_id,
            start_verifier=start_verifier,
            offering_name=offering_name,
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
            return merged

        try:
            entity = self.memory.read_condition(condition_key)
        except NotFoundError:
            return None
        return _body(entity, condition_key)


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


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewerToolError(f"{label} must be a non-empty string")
    return value.strip()
