"""Memory-backed tools used by the Standing reviewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

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
        if evaluation.state != StandingState.STANDS and action != "block":
            raise ReviewerToolError("a non-standing decision must be blocked")

        state_body = evaluation.as_dict()
        state_body["action"] = action
        state_body["explanation"] = explanation.strip()
        self.memory.save_standing(key, state_body)
        return self.memory.record_standing_change(
            evaluated={
                "decision_id": key,
                "state": evaluation.state.value,
                "fingerprint": evaluation.fingerprint,
            },
            acted={"action": action, "explanation": explanation.strip()},
            forward={"state": evaluation.state.value},
            extra={"condition_states": [condition.state.value for condition in evaluation.conditions]},
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
