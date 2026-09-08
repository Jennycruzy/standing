"""Pure evaluation of the four conditions Standing can check."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Sequence


class StandingState(StrEnum):
    """The only four standing states exposed by Standing."""

    STANDS = "STANDS"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    CONTESTED = "CONTESTED"


SUPPORTED_PROVENANCE = frozenset({"EXPLICIT", "CONFIRMED", "INFERRED", "EXTERNAL"})
BLOCKING_PROVENANCE = frozenset({"EXPLICIT", "CONFIRMED"})


@dataclass(frozen=True)
class _ParsedPredicate:
    kind: str
    expected: int | str | date


@dataclass(frozen=True)
class ConditionResult:
    """The checkable result for one condition in a decision."""

    condition_key: str
    predicate: str
    provenance: str
    required: bool
    state: StandingState
    blocks: bool
    evaluated: bool
    accepted_value: Any
    source_url: str | None
    observation_uids: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "predicate": self.predicate,
            "provenance": self.provenance,
            "required": self.required,
            "state": self.state.value,
            "blocks": self.blocks,
            "evaluated": self.evaluated,
            "accepted_value": _stable_value(self.accepted_value),
            "source_url": self.source_url,
            "observation_uids": list(self.observation_uids),
            "message": self.message,
        }


@dataclass(frozen=True)
class StandingEvaluation:
    """A deterministic standing result and the evidence for each condition."""

    decision_id: str
    state: StandingState
    conditions: tuple[ConditionResult, ...]
    notes: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "state": self.state.value,
            "conditions": [condition.as_dict() for condition in self.conditions],
            "notes": list(self.notes),
        }

    @property
    def fingerprint(self) -> str:
        """Return the same digest for the same decision and condition values."""

        encoded = json.dumps(
            self._payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        result = self._payload()
        result["fingerprint"] = self.fingerprint
        return result


def evaluate_standing(
    decision: Mapping[str, Any],
    conditions: Mapping[str, Mapping[str, Any]],
) -> StandingEvaluation:
    """Evaluate a decision without I/O, model calls, or writes.

    ``decision["conditions"]`` contains the human-approved condition rules.
    ``conditions`` contains the current accepted records keyed by condition key.
    A missing or unusable current value is UNKNOWN. Disagreeing observations are
    CONTESTED. A failed condition can affect the decision only when it is both
    required and EXPLICIT or CONFIRMED.
    """

    decision_id = _decision_id(decision)
    raw_specs = decision.get("conditions")
    if not isinstance(raw_specs, Sequence) or isinstance(raw_specs, (str, bytes)):
        raise ValueError("decision.conditions must be a list of condition records")

    results: list[ConditionResult] = []
    notes: list[str] = []
    for raw_spec in raw_specs:
        if not isinstance(raw_spec, Mapping):
            raise ValueError("each decision condition must be a mapping")
        spec = _condition_spec(raw_spec)
        current = conditions.get(spec["condition_key"])
        result = _evaluate_condition(spec, current)
        results.append(result)
        if not result.blocks and (result.state != StandingState.STANDS or not result.evaluated):
            notes.append(result.message)

    state = _decision_state(results)
    return StandingEvaluation(decision_id, state, tuple(results), tuple(notes))


def _decision_id(decision: Mapping[str, Any]) -> str:
    for field in ("decision_id", "id", "name"):
        value = decision.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("decision must contain a non-empty decision_id, id, or name")


def _condition_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    key = spec.get("condition_key")
    predicate = spec.get("predicate")
    provenance = spec.get("provenance")
    required = spec.get("required")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("condition_key must be a non-empty string")
    if not isinstance(predicate, str) or not predicate.strip():
        raise ValueError(f"predicate for {key} must be a non-empty string")
    if not isinstance(provenance, str) or provenance not in SUPPORTED_PROVENANCE:
        raise ValueError(f"provenance for {key} must be one of {sorted(SUPPORTED_PROVENANCE)}")
    if not isinstance(required, bool):
        raise ValueError(f"required for {key} must be true or false")
    return {
        "condition_key": key.strip(),
        "predicate": predicate.strip(),
        "provenance": provenance,
        "required": required,
    }


def _evaluate_condition(
    spec: Mapping[str, Any],
    current: Mapping[str, Any] | None,
) -> ConditionResult:
    key = _as_string(spec["condition_key"])
    predicate = _as_string(spec["predicate"])
    provenance = _as_string(spec["provenance"])
    required = _as_bool(spec["required"])
    blocking_allowed = required and provenance in BLOCKING_PROVENANCE

    if current is None:
        state = StandingState.UNKNOWN
        message = f'The current value for "{key}" could not be established.'
        return _result(spec, state, blocking_allowed, False, None, None, (), _with_limit(message, blocking_allowed))

    source_url = _optional_string(current, "accepted_source_url", "source_url")
    observation_uids = _observation_uids(current)
    accepted_value = current.get("accepted_value")
    parsed = _parse_predicate(predicate)

    if parsed is None:
        message = (
            f'The condition "{key}" uses a rule outside Standing\'s four supported checks; '
            "it is recorded as a note and cannot block."
        )
        return _result(
            spec,
            StandingState.STANDS,
            False,
            False,
            accepted_value,
            source_url,
            observation_uids,
            message,
        )

    if _is_contested(current):
        state = StandingState.CONTESTED
        message = f'Observations for "{key}" disagree, so Standing will not choose between them.'
        return _result(
            spec,
            state,
            blocking_allowed,
            True,
            accepted_value,
            source_url,
            observation_uids,
            _with_limit(message, blocking_allowed),
        )

    if "accepted_value" not in current or accepted_value is None:
        state = StandingState.UNKNOWN
        message = f'The current value for "{key}" could not be established.'
        return _result(
            spec,
            state,
            blocking_allowed,
            True,
            accepted_value,
            source_url,
            observation_uids,
            _with_limit(message, blocking_allowed),
        )

    passed = _matches(parsed, accepted_value)
    if passed is None:
        state = StandingState.UNKNOWN
        message = f'The current value for "{key}" could not be established.'
    elif passed:
        state = StandingState.STANDS
        message = f'The current value for "{key}" satisfies {predicate}.'
    else:
        state = StandingState.EXPIRED
        message = f'The current value for "{key}" does not satisfy {predicate}.'

    return _result(
        spec,
        state,
        blocking_allowed and state != StandingState.STANDS,
        True,
        accepted_value,
        source_url,
        observation_uids,
        _with_limit(message, blocking_allowed),
    )


def _result(
    spec: Mapping[str, Any],
    state: StandingState,
    blocks: bool,
    evaluated: bool,
    accepted_value: Any,
    source_url: str | None,
    observation_uids: tuple[str, ...],
    message: str,
) -> ConditionResult:
    return ConditionResult(
        condition_key=_as_string(spec["condition_key"]),
        predicate=_as_string(spec["predicate"]),
        provenance=_as_string(spec["provenance"]),
        required=_as_bool(spec["required"]),
        state=state,
        blocks=blocks,
        evaluated=evaluated,
        accepted_value=accepted_value,
        source_url=source_url,
        observation_uids=observation_uids,
        message=message,
    )


def _decision_state(results: Sequence[ConditionResult]) -> StandingState:
    priority = {
        StandingState.STANDS: 0,
        StandingState.EXPIRED: 1,
        StandingState.UNKNOWN: 2,
        StandingState.CONTESTED: 3,
    }
    blocking = [result.state for result in results if result.blocks]
    if not blocking:
        return StandingState.STANDS
    return max(blocking, key=priority.__getitem__)


def _parse_predicate(predicate: str) -> _ParsedPredicate | None:
    retention = re.fullmatch(r"retention_days\s*>=\s*(\d+)", predicate)
    if retention is not None:
        return _ParsedPredicate("retention_days", int(retention.group(1)))

    regions = re.fullmatch(r'regions\s+contains\s+"([^"]+)"', predicate)
    if regions is not None:
        return _ParsedPredicate("regions", regions.group(1))

    if re.fullmatch(r"supports_sso\s*==\s*true", predicate) is not None:
        return _ParsedPredicate("supports_sso", "true")

    eol = re.fullmatch(r"eol_date\s*>\s*(\d{4}-\d{2}-\d{2})", predicate)
    if eol is not None:
        return _ParsedPredicate("eol_date", date.fromisoformat(eol.group(1)))

    return None


def _matches(predicate: _ParsedPredicate, value: Any) -> bool | None:
    if predicate.kind == "retention_days":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(float(value)):
            return None
        expected = predicate.expected
        if not isinstance(expected, int):
            raise TypeError("retention predicate threshold must be an integer")
        return float(value) >= expected

    if predicate.kind == "regions":
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            return None
        expected = predicate.expected
        if not isinstance(expected, str):
            raise TypeError("region predicate target must be a string")
        return expected in value

    if predicate.kind == "supports_sso":
        return bool(value) if isinstance(value, bool) else None

    if predicate.kind == "eol_date":
        if not isinstance(value, str):
            return None
        try:
            observed = date.fromisoformat(value)
        except ValueError:
            return None
        expected = predicate.expected
        if not isinstance(expected, date):
            raise TypeError("end-of-life predicate threshold must be a date")
        return observed > expected

    raise ValueError(f"unsupported parsed predicate kind: {predicate.kind}")


def _is_contested(current: Mapping[str, Any]) -> bool:
    if current.get("acceptance_status") == StandingState.CONTESTED.value:
        return True
    observations = current.get("observations")
    if observations is None:
        return False
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise ValueError("condition observations must be a list")
    values = [observation.get("value") for observation in observations if isinstance(observation, Mapping)]
    if len(values) != len(observations):
        raise ValueError("each condition observation must be a mapping")
    return len({_canonical_json(value) for value in values}) > 1


def _observation_uids(current: Mapping[str, Any]) -> tuple[str, ...]:
    raw_uids = current.get("observation_uids")
    if raw_uids is None:
        observations = current.get("observations")
        if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
            return ()
        raw_uids = [observation.get("observation_uid") for observation in observations if isinstance(observation, Mapping)]
    if not isinstance(raw_uids, Sequence) or isinstance(raw_uids, (str, bytes)):
        raise ValueError("observation_uids must be a list")
    uids: list[str] = []
    for uid in raw_uids:
        if uid is None:
            continue
        if not isinstance(uid, str) or not uid.strip():
            raise ValueError("each observation UID must be a non-empty string")
        uids.append(uid)
    return tuple(uids)


def _optional_string(current: Mapping[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = current.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string when supplied")
            return value.strip()
    return None


def _with_limit(message: str, blocking_allowed: bool) -> str:
    if blocking_allowed:
        return message
    return f"{message} This condition cannot block this decision."


def _as_string(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def _as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected a boolean")
    return value


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
    raise TypeError(f"value of type {type(value).__name__} cannot be fingerprinted")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _stable_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
