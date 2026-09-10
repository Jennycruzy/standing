"""Advisory model review and human-confirmed extraction boundaries.

The model is allowed to suggest what a reviewer should inspect and what a
source appears to say. It is not allowed to decide standing, write memory, or
approve evidence. Promotion of an extraction requires an explicit human
confirmation and the bytes of the source snapshot that was reviewed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ModelReviewError(RuntimeError):
    """Raised when the model boundary returns unusable or unsafe data."""


class _HttpResponse(Protocol):
    def read(self) -> bytes:
        ...


class _UrlOpener(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> _HttpResponse:
        ...


class ResponsesTransport(Protocol):
    """Small injectable transport used by the model boundary and its tests."""

    def complete(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> ModelCompletion:
        ...


@dataclass(frozen=True)
class ModelCompletion:
    """The structured JSON returned by a model transport."""

    response_id: str | None
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.response_id is not None and not self.response_id.strip():
            raise ModelReviewError("response_id must be non-empty when supplied")
        if not isinstance(self.data, Mapping):
            raise ModelReviewError("model completion data must be an object")


class OpenAIResponsesClient:
    """Minimal Responses API client using only the standard library.

    The API key is accepted from the environment and is never included in
    errors, model prompts, or serialized proposal records.
    """

    DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: int = 60,
        opener: _UrlOpener | None = None,
    ) -> None:
        self._api_key = _required_string(api_key, "api_key")
        self._endpoint = _https_url(endpoint, "endpoint")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ModelReviewError("timeout_seconds must be a positive integer")
        self._timeout_seconds = timeout_seconds
        self._opener = opener or cast(_UrlOpener, urlopen)

    @classmethod
    def from_env(
        cls,
        *,
        env_name: str = "OPENAI_API_KEY",
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: int = 60,
        opener: _UrlOpener | None = None,
    ) -> OpenAIResponsesClient:
        """Construct a client without ever exposing the environment value."""

        name = _required_string(env_name, "env_name")
        api_key = os.environ.get(name)
        if api_key is None or not api_key.strip():
            raise ModelReviewError(f"environment variable {name} is missing")
        return cls(
            api_key,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
        )

    def complete(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> ModelCompletion:
        model_name = _required_string(model, "model")
        instruction_text = _required_string(instructions, "instructions")
        request_text = _required_string(input_text, "input_text")
        output_schema_name = _required_string(schema_name, "schema_name")
        if not isinstance(schema, Mapping):
            raise ModelReviewError("schema must be an object")

        body = {
            "model": model_name,
            "instructions": instruction_text,
            "input": request_text,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": output_schema_name,
                    "strict": True,
                    "schema": dict(schema),
                }
            },
        }
        request = Request(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = self._opener(request, timeout=float(self._timeout_seconds))
            raw_response = response.read()
        except HTTPError as error:
            raise ModelReviewError(f"model request failed with HTTP {error.code}") from error
        except URLError as error:
            raise ModelReviewError("model request could not reach the endpoint") from error
        except OSError as error:
            raise ModelReviewError("model request failed while reading the response") from error

        try:
            decoded: Any = json.loads(raw_response)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelReviewError("model response was not valid JSON") from error
        if not isinstance(decoded, Mapping):
            raise ModelReviewError("model response must be an object")
        response_id = decoded.get("id")
        if response_id is not None and not isinstance(response_id, str):
            raise ModelReviewError("model response id must be a string")
        output_text = _response_output_text(decoded)
        try:
            output: Any = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ModelReviewError("model structured output was not valid JSON") from error
        if not isinstance(output, Mapping):
            raise ModelReviewError("model structured output must be an object")
        return ModelCompletion(response_id, dict(output))


@dataclass(frozen=True)
class ReviewContext:
    """The bounded, non-secret context supplied to an advisory reviewer."""

    changed_paths: tuple[str, ...]
    candidate_decisions: tuple[Mapping[str, Any], ...]
    boot_changes: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _string_tuple(self.changed_paths, "changed_paths", allow_empty=False)
        for index, decision in enumerate(self.candidate_decisions):
            _json_mapping(decision, f"candidate_decisions[{index}]")
            _decision_id(decision)
        for index, change in enumerate(self.boot_changes):
            _json_mapping(change, f"boot_changes[{index}]")

    @property
    def candidate_decision_ids(self) -> tuple[str, ...]:
        return tuple(_decision_id(decision) for decision in self.candidate_decisions)

    @property
    def candidate_condition_keys(self) -> tuple[str, ...]:
        keys: set[str] = set()
        for decision in self.candidate_decisions:
            raw_conditions = decision.get("conditions", [])
            if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
                raise ModelReviewError(
                    f"conditions for {_decision_id(decision)} must be a list"
                )
            for index, raw_condition in enumerate(raw_conditions):
                if not isinstance(raw_condition, Mapping):
                    raise ModelReviewError(
                        f"condition {index} for {_decision_id(decision)} must be an object"
                    )
                keys.add(_required_string(raw_condition.get("condition_key"), "condition_key"))
        return tuple(sorted(keys))

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed_paths": list(self.changed_paths),
            "candidate_decisions": [dict(decision) for decision in self.candidate_decisions],
            "boot_changes": [dict(change) for change in self.boot_changes],
        }


REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision_ids": {"type": "array", "items": {"type": "string"}},
        "condition_keys": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["decision_ids", "condition_keys", "questions", "rationale"],
}


_REVIEW_INSTRUCTIONS = """You are an advisory reviewer for the Standing project.
Select only supplied decision IDs and condition keys that deserve human review.
Explain the evidence gap or inconsistency and ask focused questions.
This output is not a verdict: never emit a standing state, allow/block action,
approval, or a claim that evidence is accepted. Do not invent identifiers.
Return only the requested structured object."""


@dataclass(frozen=True)
class ReviewProposal:
    """A model suggestion that contains no authority to change standing."""

    decision_ids: tuple[str, ...]
    condition_keys: tuple[str, ...]
    questions: tuple[str, ...]
    rationale: str
    model_id: str
    response_id: str | None = None

    def __post_init__(self) -> None:
        _string_tuple(self.decision_ids, "decision_ids")
        _string_tuple(self.condition_keys, "condition_keys")
        _string_tuple(self.questions, "questions")
        _required_string(self.rationale, "rationale")
        _required_string(self.model_id, "model_id")
        if self.response_id is not None:
            _required_string(self.response_id, "response_id")

    @classmethod
    def from_completion(
        cls,
        completion: ModelCompletion,
        *,
        model_id: str,
        known_decision_ids: Sequence[str],
        known_condition_keys: Sequence[str],
    ) -> ReviewProposal:
        raw = _exact_mapping(
            completion.data,
            {"decision_ids", "condition_keys", "questions", "rationale"},
            "review output",
        )
        decision_ids = _string_tuple(raw.get("decision_ids"), "decision_ids")
        condition_keys = _string_tuple(raw.get("condition_keys"), "condition_keys")
        questions = _string_tuple(raw.get("questions"), "questions")
        known_decisions = set(known_decision_ids)
        known_conditions = set(known_condition_keys)
        unknown_decisions = sorted(set(decision_ids) - known_decisions)
        unknown_conditions = sorted(set(condition_keys) - known_conditions)
        if unknown_decisions:
            raise ModelReviewError(
                "model selected unknown decision IDs: " + ", ".join(unknown_decisions)
            )
        if unknown_conditions:
            raise ModelReviewError(
                "model selected unknown condition keys: " + ", ".join(unknown_conditions)
            )
        return cls(
            decision_ids=decision_ids,
            condition_keys=condition_keys,
            questions=questions,
            rationale=_required_string(raw.get("rationale"), "rationale"),
            model_id=_required_string(model_id, "model_id"),
            response_id=completion.response_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_ids": list(self.decision_ids),
            "condition_keys": list(self.condition_keys),
            "questions": list(self.questions),
            "rationale": self.rationale,
            "model_id": self.model_id,
            "response_id": self.response_id,
        }


class ModelReviewer:
    """Call an advisory model and validate its selections against context."""

    def __init__(self, transport: ResponsesTransport, *, model_id: str) -> None:
        self.transport = transport
        self.model_id = _required_string(model_id, "model_id")

    def review(self, context: ReviewContext) -> ReviewProposal:
        if not isinstance(context, ReviewContext):
            raise ModelReviewError("review context must be a ReviewContext")
        input_text = _json_text({"task": "select review targets", "context": context.as_dict()})
        completion = self.transport.complete(
            model=self.model_id,
            instructions=_REVIEW_INSTRUCTIONS,
            input_text=input_text,
            schema_name="standing_review_proposal",
            schema=REVIEW_OUTPUT_SCHEMA,
        )
        return ReviewProposal.from_completion(
            completion,
            model_id=self.model_id,
            known_decision_ids=context.candidate_decision_ids,
            known_condition_keys=context.candidate_condition_keys,
        )


DECISION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision_id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "governed_paths": {"type": "array", "items": {"type": "string"}},
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "condition_key": {"type": "string"},
                    "predicate": {"type": "string"},
                    "required": {"type": "boolean"},
                    "provenance": {"type": "string"},
                    "unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["condition_key", "predicate", "required", "provenance", "unit"],
            },
        },
        "source_sentence": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": [
        "decision_id",
        "title",
        "description",
        "governed_paths",
        "conditions",
        "source_sentence",
        "rationale",
    ],
}


_DECISION_INSTRUCTIONS = """You are an advisory decision extractor for Standing.
Read the supplied engineering artifact and propose one decision envelope only
when the artifact explicitly states a technical choice, its rationale, the
paths it governs, and the assumptions it depends on. Do not infer a blocking
assumption from code alone. Mark every proposed condition as INFERRED unless
the artifact clearly states it as an explicit requirement; even EXPLICIT text
still requires human confirmation before governance. Do not emit a standing
state, allow/block action, waiver, approval, or memory write. Use only paths and
condition facts present in the artifact. Return a focused rationale and the
exact source sentence supporting the proposal."""


@dataclass(frozen=True)
class DecisionProposal:
    """A model-proposed decision envelope awaiting human confirmation."""

    decision_id: str
    title: str
    description: str
    governed_paths: tuple[str, ...]
    conditions: tuple[Mapping[str, Any], ...]
    artifact_path: str
    artifact_type: str
    artifact_sha256: str
    source_sentence: str
    rationale: str
    model_id: str
    response_id: str | None = None
    status: str = "PENDING"

    def __post_init__(self) -> None:
        _required_string(self.decision_id, "decision_id")
        _required_string(self.title, "title")
        _required_string(self.description, "description")
        _string_tuple(self.governed_paths, "governed_paths", allow_empty=False)
        if not self.conditions:
            raise ModelReviewError("decision proposal must contain at least one condition")
        for index, condition in enumerate(self.conditions):
            _validate_proposed_condition(condition, index)
        _required_string(self.artifact_path, "artifact_path")
        _required_string(self.artifact_type, "artifact_type")
        _sha256_digest(self.artifact_sha256, "artifact_sha256")
        _required_string(self.source_sentence, "source_sentence")
        _required_string(self.rationale, "rationale")
        _required_string(self.model_id, "model_id")
        if self.response_id is not None:
            _required_string(self.response_id, "response_id")
        if self.status not in {"PENDING", "CONFIRMED", "REJECTED"}:
            raise ModelReviewError("decision proposal status is invalid")

    @classmethod
    def from_completion(
        cls,
        completion: ModelCompletion,
        *,
        model_id: str,
        artifact_path: str,
        artifact_type: str,
        artifact_sha256: str,
    ) -> DecisionProposal:
        raw = _exact_mapping(completion.data, set(DECISION_OUTPUT_SCHEMA["required"]), "decision output")
        paths = _string_tuple(raw.get("governed_paths"), "governed_paths", allow_empty=False)
        raw_conditions = raw.get("conditions")
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise ModelReviewError("decision proposal conditions must be a list")
        conditions: list[Mapping[str, Any]] = []
        for index, raw_condition in enumerate(raw_conditions):
            if not isinstance(raw_condition, Mapping):
                raise ModelReviewError(f"decision proposal condition {index} must be an object")
            _validate_proposed_condition(raw_condition, index)
            condition = dict(raw_condition)
            if condition.get("unit") is not None:
                condition["unit"] = _required_string(condition.get("unit"), f"conditions[{index}].unit")
            conditions.append(condition)
        return cls(
            decision_id=_required_string(raw.get("decision_id"), "decision_id"),
            title=_required_string(raw.get("title"), "title"),
            description=_required_string(raw.get("description"), "description"),
            governed_paths=paths,
            conditions=tuple(conditions),
            artifact_path=_required_string(artifact_path, "artifact_path"),
            artifact_type=_required_string(artifact_type, "artifact_type"),
            artifact_sha256=_sha256_digest(artifact_sha256, "artifact_sha256"),
            source_sentence=_required_string(raw.get("source_sentence"), "source_sentence"),
            rationale=_required_string(raw.get("rationale"), "rationale"),
            model_id=_required_string(model_id, "model_id"),
            response_id=completion.response_id,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DecisionProposal:
        """Parse a persisted proposal and verify its optional fingerprint."""

        if not isinstance(raw, Mapping):
            raise ModelReviewError("decision proposal must be an object")
        raw_conditions = raw.get("conditions")
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise ModelReviewError("decision proposal conditions must be a list")
        conditions: list[Mapping[str, Any]] = []
        for index, raw_condition in enumerate(raw_conditions):
            if not isinstance(raw_condition, Mapping):
                raise ModelReviewError(f"decision proposal condition {index} must be an object")
            _validate_proposed_condition(raw_condition, index)
            conditions.append(dict(raw_condition))
        response_id_raw = raw.get("response_id")
        response_id = None if response_id_raw is None else _required_string(response_id_raw, "response_id")
        proposal = cls(
            decision_id=_required_string(raw.get("decision_id"), "decision_id"),
            title=_required_string(raw.get("title"), "title"),
            description=_required_string(raw.get("description"), "description"),
            governed_paths=_string_tuple(raw.get("governed_paths"), "governed_paths", allow_empty=False),
            conditions=tuple(conditions),
            artifact_path=_required_string(raw.get("artifact_path"), "artifact_path"),
            artifact_type=_required_string(raw.get("artifact_type"), "artifact_type"),
            artifact_sha256=_sha256_digest(raw.get("artifact_sha256"), "artifact_sha256"),
            source_sentence=_required_string(raw.get("source_sentence"), "source_sentence"),
            rationale=_required_string(raw.get("rationale"), "rationale"),
            model_id=_required_string(raw.get("model_id"), "model_id"),
            response_id=response_id,
            status=_required_string(raw.get("status", "PENDING"), "status"),
        )
        fingerprint = raw.get("proposal_fingerprint")
        if fingerprint is not None and _required_string(fingerprint, "proposal_fingerprint") != proposal.fingerprint:
            raise ModelReviewError("decision proposal fingerprint does not match its contents")
        return proposal

    @property
    def proposal_id(self) -> str:
        """Return a stable ID that binds the proposal to its artifact snapshot."""

        return f"proposal:{self.fingerprint}"

    @property
    def fingerprint(self) -> str:
        return _sha256(self._fingerprint_payload())

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "description": self.description,
            "governed_paths": list(self.governed_paths),
            "conditions": [dict(condition) for condition in self.conditions],
            "artifact_path": self.artifact_path,
            "artifact_type": self.artifact_type,
            "artifact_sha256": self.artifact_sha256,
            "source_sentence": self.source_sentence,
            "rationale": self.rationale,
            "model_id": self.model_id,
            "response_id": self.response_id,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "decision_id": self.decision_id,
            "title": self.title,
            "description": self.description,
            "governed_paths": list(self.governed_paths),
            "conditions": [dict(condition) for condition in self.conditions],
            "artifact_path": self.artifact_path,
            "artifact_type": self.artifact_type,
            "artifact_sha256": self.artifact_sha256,
            "source_sentence": self.source_sentence,
            "rationale": self.rationale,
            "model_id": self.model_id,
            "response_id": self.response_id,
            "status": self.status,
            "proposal_fingerprint": self.fingerprint,
        }


class ModelDecisionExtractor:
    """Generate a decision proposal from a captured artifact without writing it."""

    MAX_SOURCE_CHARS = 200_000

    def __init__(self, transport: ResponsesTransport, *, model_id: str) -> None:
        self.transport = transport
        self.model_id = _required_string(model_id, "model_id")

    def propose(
        self,
        *,
        artifact_path: str,
        artifact_type: str,
        artifact_text: str,
        artifact_sha256: str,
    ) -> DecisionProposal:
        path = _required_string(artifact_path, "artifact_path")
        kind = _required_string(artifact_type, "artifact_type")
        text = _required_string(artifact_text, "artifact_text")
        if len(text) > self.MAX_SOURCE_CHARS:
            raise ModelReviewError(
                f"artifact_text exceeds the {self.MAX_SOURCE_CHARS}-character limit"
            )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest.lower() != _sha256_digest(artifact_sha256, "artifact_sha256").lower():
            raise ModelReviewError("artifact_sha256 does not match the supplied artifact text")
        completion = self.transport.complete(
            model=self.model_id,
            instructions=_DECISION_INSTRUCTIONS,
            input_text=_json_text(
                {
                    "task": "propose one decision envelope",
                    "artifact": {
                        "path": path,
                        "artifact_type": kind,
                        "sha256": digest,
                        "text": text,
                    },
                }
            ),
            schema_name="standing_decision_proposal",
            schema=DECISION_OUTPUT_SCHEMA,
        )
        return DecisionProposal.from_completion(
            completion,
            model_id=self.model_id,
            artifact_path=path,
            artifact_type=kind,
            artifact_sha256=digest,
        )


EXTRACTION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "condition_key": {"type": "string"},
        "value_json": {"type": "string"},
        "source_url": {"type": "string"},
        "effective_from": {"type": "integer"},
        "rationale": {"type": "string"},
    },
    "required": ["condition_key", "value_json", "source_url", "effective_from", "rationale"],
}


_EXTRACTION_INSTRUCTIONS = """You are an advisory source extractor for Standing.
Read the supplied source text and propose the value for the requested
condition. Return the value encoded as JSON in value_json, preserving its
type. Use the supplied source URL exactly and provide the source's effective
Unix timestamp when it is explicit. If the source does not establish a value,
do not guess: return a rationale explaining the gap. This is only a proposal;
it is not verified evidence and cannot authorize any action."""


@dataclass(frozen=True)
class ExtractionProposal:
    """A model's source-reading proposal awaiting human confirmation."""

    condition_key: str
    value: Any
    source_url: str
    effective_from: int
    rationale: str
    model_id: str
    response_id: str | None = None

    def __post_init__(self) -> None:
        _required_string(self.condition_key, "condition_key")
        if self.value is None:
            raise ModelReviewError("extraction value must not be null")
        _json_value(self.value, "extraction value")
        _https_url(self.source_url, "source_url")
        _nonnegative_int(self.effective_from, "effective_from")
        _required_string(self.rationale, "rationale")
        _required_string(self.model_id, "model_id")
        if self.response_id is not None:
            _required_string(self.response_id, "response_id")

    @classmethod
    def from_completion(
        cls,
        completion: ModelCompletion,
        *,
        model_id: str,
        expected_condition_key: str,
        expected_source_url: str,
    ) -> ExtractionProposal:
        raw = _exact_mapping(
            completion.data,
            {"condition_key", "value_json", "source_url", "effective_from", "rationale"},
            "extraction output",
        )
        condition_key = _required_string(raw.get("condition_key"), "condition_key")
        expected_key = _required_string(expected_condition_key, "expected_condition_key")
        if condition_key != expected_key:
            raise ModelReviewError("model returned a different condition key")
        source_url = _https_url(raw.get("source_url"), "source_url")
        expected_url = _https_url(expected_source_url, "expected_source_url")
        if source_url.rstrip("/") != expected_url.rstrip("/"):
            raise ModelReviewError("model returned a different source URL")
        value_json = _required_string(raw.get("value_json"), "value_json")
        try:
            value: Any = json.loads(value_json)
        except json.JSONDecodeError as error:
            raise ModelReviewError("value_json is not valid JSON") from error
        if value is None:
            raise ModelReviewError("value_json must not encode null")
        return cls(
            condition_key=condition_key,
            value=value,
            source_url=expected_url,
            effective_from=_nonnegative_int(raw.get("effective_from"), "effective_from"),
            rationale=_required_string(raw.get("rationale"), "rationale"),
            model_id=_required_string(model_id, "model_id"),
            response_id=completion.response_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "value": _json_value(self.value, "extraction value"),
            "source_url": self.source_url,
            "effective_from": self.effective_from,
            "rationale": self.rationale,
            "model_id": self.model_id,
            "response_id": self.response_id,
            "proposal_fingerprint": self.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return _sha256(self._fingerprint_payload())

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "condition_key": self.condition_key,
            "value": _json_value(self.value, "extraction value"),
            "source_url": self.source_url,
            "effective_from": self.effective_from,
            "rationale": self.rationale,
            "model_id": self.model_id,
            "response_id": self.response_id,
        }


class ModelExtractor:
    """Generate a typed proposal from source text without persisting it."""

    MAX_SOURCE_CHARS = 200_000

    def __init__(self, transport: ResponsesTransport, *, model_id: str) -> None:
        self.transport = transport
        self.model_id = _required_string(model_id, "model_id")

    def propose(
        self,
        *,
        condition_key: str,
        predicate: str,
        source_url: str,
        source_text: str,
    ) -> ExtractionProposal:
        key = _required_string(condition_key, "condition_key")
        predicate_text = _required_string(predicate, "predicate")
        url = _https_url(source_url, "source_url")
        text = _required_string(source_text, "source_text")
        if len(text) > self.MAX_SOURCE_CHARS:
            raise ModelReviewError(
                f"source_text exceeds the {self.MAX_SOURCE_CHARS}-character limit"
            )
        input_text = _json_text(
            {
                "task": "propose one source-linked condition value",
                "condition": {"condition_key": key, "predicate": predicate_text},
                "source_url": url,
                "source_text": text,
            }
        )
        completion = self.transport.complete(
            model=self.model_id,
            instructions=_EXTRACTION_INSTRUCTIONS,
            input_text=input_text,
            schema_name="standing_extraction_proposal",
            schema=EXTRACTION_OUTPUT_SCHEMA,
        )
        return ExtractionProposal.from_completion(
            completion,
            model_id=self.model_id,
            expected_condition_key=key,
            expected_source_url=url,
        )


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_DISALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "example.com", "example.org"})


@dataclass(frozen=True)
class ConfirmedExtraction:
    """A human-confirmed extraction ready for an explicit caller write."""

    proposal: ExtractionProposal
    source_type: str
    publisher_id: str | None
    confirmed_by: str
    confirmed_at: int
    source_sha256: str
    confirmation_id: str
    review_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, ExtractionProposal):
            raise ModelReviewError("proposal must be an ExtractionProposal")
        _required_string(self.source_type, "source_type")
        if self.publisher_id is not None:
            _required_string(self.publisher_id, "publisher_id")
        _required_string(self.confirmed_by, "confirmed_by")
        _nonnegative_int(self.confirmed_at, "confirmed_at")
        _sha256_digest(self.source_sha256, "source_sha256")
        _required_string(self.confirmation_id, "confirmation_id")
        _required_string(self.review_note, "review_note")

    @property
    def observation_uid(self) -> str:
        return f"extraction-confirmed:{self.confirmation_id}"

    @property
    def confirmation_fingerprint(self) -> str:
        return _sha256(
            {
                "confirmation_id": self.confirmation_id,
                "proposal_fingerprint": self.proposal.fingerprint,
                "source_sha256": self.source_sha256,
                "source_type": self.source_type,
                "publisher_id": self.publisher_id,
                "confirmed_by": self.confirmed_by,
                "confirmed_at": self.confirmed_at,
                "review_note": self.review_note,
            }
        )

    def as_condition_reference(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return body/metadata for an explicit MemoryStore reference write."""

        body = {
            "accepted_value": _json_value(self.proposal.value, "extraction value"),
            "accepted_source_url": self.proposal.source_url,
            "observation_uids": [self.observation_uid],
        }
        metadata: dict[str, Any] = {
            "source_type": self.source_type,
            "source_sha256": self.source_sha256,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
            "confirmation_id": self.confirmation_id,
            "confirmation_fingerprint": self.confirmation_fingerprint,
            "model_proposal_fingerprint": self.proposal.fingerprint,
            "model_id": self.proposal.model_id,
            "review_note": self.review_note,
        }
        if self.publisher_id is not None:
            metadata["publisher_id"] = self.publisher_id
        return body, metadata

    def as_observation(self) -> dict[str, Any]:
        """Return a checked observation payload for a caller-controlled write."""

        observation: dict[str, Any] = {
            "condition_key": self.proposal.condition_key,
            "observation_uid": self.observation_uid,
            "value": _json_value(self.proposal.value, "extraction value"),
            "source_type": self.source_type,
            "source_url": self.proposal.source_url,
            "effective_from": self.proposal.effective_from,
            "note": self.review_note,
            "provenance": {
                "operator_id": self.confirmed_by,
                "source_id": self.proposal.source_url,
                "extractor_id": f"human-confirmed:{self.proposal.model_id}",
            },
        }
        if self.publisher_id is not None:
            observation["publisher_id"] = self.publisher_id
        return observation


def confirm_extraction(
    proposal: ExtractionProposal,
    *,
    source_snapshot: bytes,
    confirmed_by: str,
    confirmed_at: int,
    source_type: str = "vendor_primary",
    publisher_id: str | None = None,
    review_note: str,
) -> ConfirmedExtraction:
    """Require explicit human review and hash the exact reviewed source bytes."""

    if not isinstance(proposal, ExtractionProposal):
        raise ModelReviewError("proposal must be an ExtractionProposal")
    if not isinstance(source_snapshot, bytes) or not source_snapshot:
        raise ModelReviewError("source_snapshot must be non-empty bytes")
    source_sha256 = hashlib.sha256(source_snapshot).hexdigest()
    source_type_value = _required_string(source_type, "source_type")
    confirmed_by_value = _required_string(confirmed_by, "confirmed_by")
    confirmed_at_value = _nonnegative_int(confirmed_at, "confirmed_at")
    note = _required_string(review_note, "review_note")
    publisher = None if publisher_id is None else _required_string(publisher_id, "publisher_id")
    confirmation_payload = {
        "proposal_fingerprint": proposal.fingerprint,
        "source_sha256": source_sha256,
        "source_type": source_type_value,
        "publisher_id": publisher,
        "confirmed_by": confirmed_by_value,
        "confirmed_at": confirmed_at_value,
        "review_note": note,
    }
    confirmation_id = f"human-{_sha256(confirmation_payload)}"
    return ConfirmedExtraction(
        proposal=proposal,
        source_type=source_type_value,
        publisher_id=publisher,
        confirmed_by=confirmed_by_value,
        confirmed_at=confirmed_at_value,
        source_sha256=source_sha256,
        confirmation_id=confirmation_id,
        review_note=note,
    )


def _response_output_text(response: Mapping[str, Any]) -> str:
    top_level = response.get("output_text")
    if isinstance(top_level, str) and top_level.strip():
        return top_level
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise ModelReviewError("model response contained no output text")


def _exact_mapping(raw: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ModelReviewError(f"{label} must be an object")
    actual = {str(key) for key in raw.keys()}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ModelReviewError(f"{label} is missing: {', '.join(missing)}")
    if extra:
        raise ModelReviewError(f"{label} contains unsupported fields: {', '.join(extra)}")
    return dict(raw)


def _string_tuple(value: Any, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ModelReviewError(f"{label} must be a list of strings")
    values = tuple(_required_string(item, f"{label} item") for item in value)
    if not allow_empty and not values:
        raise ModelReviewError(f"{label} must not be empty")
    if len(values) != len(set(values)):
        raise ModelReviewError(f"{label} must not contain duplicates")
    return values


def _decision_id(decision: Mapping[str, Any]) -> str:
    for field in ("decision_id", "id", "name"):
        value = decision.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ModelReviewError("candidate decision has no usable decision ID")


def _validate_proposed_condition(value: Any, index: int) -> None:
    label = f"conditions[{index}]"
    if not isinstance(value, Mapping):
        raise ModelReviewError(f"{label} must be an object")
    _required_string(value.get("condition_key"), f"{label}.condition_key")
    _required_string(value.get("predicate"), f"{label}.predicate")
    required = value.get("required")
    if not isinstance(required, bool):
        raise ModelReviewError(f"{label}.required must be true or false")
    provenance = _required_string(value.get("provenance"), f"{label}.provenance")
    if provenance not in {"EXPLICIT", "CONFIRMED", "INFERRED", "EXTERNAL"}:
        raise ModelReviewError(f"{label}.provenance is not a supported provenance value")
    unit = value.get("unit")
    if unit is not None:
        _required_string(unit, f"{label}.unit")


def _json_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelReviewError(f"{label} must be an object")
    _json_value(dict(value), label)
    return value


def _json_value(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ModelReviewError(f"{label} must be JSON-compatible") from error


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ModelReviewError("model input must be JSON-compatible") from error


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _sha256_digest(value: Any, label: str) -> str:
    digest = _required_string(value, label)
    if not _SHA256.fullmatch(digest):
        raise ModelReviewError(f"{label} must be a SHA-256 digest")
    return digest.lower()


def _https_url(value: Any, label: str) -> str:
    url = _required_string(value, label)
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as error:
        raise ModelReviewError(f"{label} must be a valid HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or hostname.lower() in _DISALLOWED_HOSTS
    ):
        raise ModelReviewError(f"{label} must be a public HTTPS URL without credentials")
    return url


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelReviewError(f"{label} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ModelReviewError(f"{label} must be a non-negative integer")
    return value
