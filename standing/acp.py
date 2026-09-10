"""Typed ACP verifier jobs behind the existing Python bridge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from scripts.acp_bridge import run_acp_job

from .acceptance import AcceptanceResult
from .provenance import ObservationProvenance, ProvenanceError


class AcpVerifierError(RuntimeError):
    """Raised when an ACP verifier result cannot become an observation."""


@dataclass(frozen=True)
class AcpVerifierConfig:
    """Runtime job and spend limits loaded from configuration."""

    chain_id: int
    offering_name: str
    source_type: str
    budget_usdc: float
    max_job_usdc: float
    daily_spend_usdc: float
    completion_reason: str
    timeout_seconds: float
    start_verifier: bool
    verifier_startup_timeout_seconds: float


def load_acp_config(path: str | Path) -> AcpVerifierConfig:
    """Load ACP job settings and spend caps from JSON configuration."""

    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("acp"), dict):
        raise AcpVerifierError("ACP configuration must contain an acp object")
    section = raw["acp"]
    chain_id = _positive_int(section.get("chain_id"), "chain_id")
    budget = _positive_number(section.get("budget_usdc"), "budget_usdc")
    max_job = _positive_number(section.get("max_job_usdc"), "max_job_usdc")
    daily = _positive_number(section.get("daily_spend_usdc"), "daily_spend_usdc")
    if budget > max_job:
        raise AcpVerifierError("budget_usdc exceeds max_job_usdc")
    if max_job > daily:
        raise AcpVerifierError("max_job_usdc exceeds daily_spend_usdc")
    start_verifier = section.get("start_verifier")
    if not isinstance(start_verifier, bool):
        raise AcpVerifierError("start_verifier must be true or false")
    return AcpVerifierConfig(
        chain_id=chain_id,
        offering_name=_required_string(section.get("offering_name"), "offering_name"),
        source_type=_required_string(section.get("source_type"), "source_type"),
        budget_usdc=budget,
        max_job_usdc=max_job,
        daily_spend_usdc=daily,
        completion_reason=_required_string(section.get("completion_reason"), "completion_reason"),
        timeout_seconds=_positive_number(section.get("timeout_seconds"), "timeout_seconds"),
        start_verifier=start_verifier,
        verifier_startup_timeout_seconds=_positive_number(
            section.get("verifier_startup_timeout_seconds"),
            "verifier_startup_timeout_seconds",
        ),
    )


@dataclass(frozen=True)
class VerifierObservation:
    """A verifier's signed observation returned through ACP."""

    condition_key: str
    value: Any
    source_type: str
    source_url: str
    observation_uid: str
    observer_address: str
    effective_from: int
    note: str
    disclosure: str
    job_id: str
    observation_transaction: str | None
    provenance: ObservationProvenance
    value_type: str = "number"
    unit: str | None = None
    observed_at: int | None = None
    recorded_at: int | None = None
    extraction_method: str | None = None
    extraction_version: str | None = None
    evidence_hash: str | None = None
    source_snapshot_hash: str | None = None
    source_publication_date: int | None = None
    demo_controlled: bool = False
    ref_uid: str | None = None
    source_domain: str | None = None

    def as_acceptance_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "condition_key": self.condition_key,
            "value": self.value,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "source_domain": self.source_domain or _source_domain(self.source_url),
            "observation_uid": self.observation_uid,
            "observer_address": self.observer_address,
            "attester": self.observer_address,
            "operator_id": self.provenance.operator_id,
            "effective_from": self.effective_from,
            "note": self.note,
            "notes": self.note,
            "disclosure": self.disclosure,
            "acp_job_id": self.job_id,
            "observation_transaction": self.observation_transaction,
            "provenance": self.provenance.as_dict(),
            "value_type": self.value_type,
            "unit": self.unit,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "extraction_method": self.extraction_method,
            "extraction_version": self.extraction_version,
            "evidence_hash": self.evidence_hash,
            "source_snapshot_hash": self.source_snapshot_hash,
            "source_publication_date": self.source_publication_date,
            "demo_controlled": self.demo_controlled,
            "ref_uid": self.ref_uid,
        }
        return record


class AcpRunner(Protocol):
    """The bridge call needed by the verifier client."""

    def __call__(
        self,
        request: Mapping[str, Any],
        *,
        adapter_dir: str | Path,
        environment: Mapping[str, str] | None = None,
        env_file: str | Path | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run one ACP job and return its completed response."""


class AcpVerifierClient:
    """Hire a verifier only after the caller's acceptance check is unsatisfied."""

    def __init__(
        self,
        *,
        adapter_dir: str | Path,
        config: AcpVerifierConfig,
        environment: Mapping[str, str] | None = None,
        env_file: str | Path | None = None,
        runner: AcpRunner = run_acp_job,
    ) -> None:
        self.adapter_dir = Path(adapter_dir)
        self.config = config
        self.environment = environment
        self.env_file = env_file
        self.runner = runner

    def hire_verifier(
        self,
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
        """Post one fixed-shape ACP job and require a typed delivery."""

        key = _required_string(condition_key, "condition_key")
        observer = _address(observer_address, "observer_address")
        spent = _nonnegative_number(spent_today_usdc, "spent_today_usdc")
        resume_job_id = _optional_job_id(job_id)
        if acceptance.condition_key != key:
            raise AcpVerifierError("acceptance result does not match the requested condition")
        if acceptance.accepted:
            raise AcpVerifierError("ACP hiring is not allowed after the acceptance policy succeeds")
        if self.config.budget_usdc > self.config.max_job_usdc:
            raise AcpVerifierError("configured job budget exceeds the per-job cap")
        if spent + self.config.budget_usdc > self.config.daily_spend_usdc:
            raise AcpVerifierError("daily ACP spend cap would be exceeded")
        if start_verifier is not None and not isinstance(start_verifier, bool):
            raise AcpVerifierError("start_verifier must be true or false when supplied")
        if ref_uid is not None:
            ref_uid = _uid(ref_uid, "ref_uid")
        selected_offering = (
            self.config.offering_name
            if offering_name is None
            else _required_string(offering_name, "offering_name")
        )
        requirement: dict[str, Any] = {"conditionKey": key}
        if source_url is not None or value_type is not None or unit is not None:
            if source_url is None or value_type is None or unit is None:
                raise AcpVerifierError("source_url, value_type, and unit must be supplied together")
            if not source_url.startswith(("https://", "http://")):
                raise AcpVerifierError("source_url must be HTTP or HTTPS")
            if value_type not in {"number", "boolean", "date", "set"}:
                raise AcpVerifierError("value_type is not supported")
            requirement.update({"sourceUrl": source_url, "valueType": value_type, "unit": _required_string(unit, "unit")})
        if ref_uid is not None:
            requirement["refUid"] = ref_uid
        request = {
            "chainId": self.config.chain_id,
            "offeringName": selected_offering,
            "providerAddress": observer,
            "requirement": requirement,
            "budgetUsdc": self.config.budget_usdc,
            "completionReason": self.config.completion_reason,
            "timeoutMs": int(self.config.timeout_seconds * 1000),
            "startVerifier": self.config.start_verifier if start_verifier is None else start_verifier,
            "verifierStartupTimeoutMs": int(self.config.verifier_startup_timeout_seconds * 1000),
        }
        if resume_job_id is not None:
            request["jobId"] = resume_job_id
        result = self.runner(
            request,
            adapter_dir=self.adapter_dir,
            environment=self.environment,
            env_file=self.env_file,
            timeout_seconds=self.config.timeout_seconds,
        )
        observation = parse_verifier_delivery(
            result,
            condition_key=key,
            expected_source_type=self.config.source_type,
            expected_value_type=value_type,
            expected_unit=unit,
        )
        if observation.observer_address.lower() != observer.lower():
            raise AcpVerifierError("verifier delivery was signed by a different observer")
        return observation


def parse_verifier_delivery(
    result: Mapping[str, Any],
    *,
    condition_key: str,
    expected_source_type: str,
    expected_value_type: str | None = None,
    expected_unit: str | None = None,
) -> VerifierObservation:
    """Extract one JSON verifier delivery from a completed ACP result."""

    key = _required_string(condition_key, "condition_key")
    source_type = _required_string(expected_source_type, "expected_source_type")
    job_id = _required_string(result.get("jobId"), "ACP jobId")
    if result.get("status") != "completed":
        raise AcpVerifierError("ACP result is not completed")
    entries = result.get("entries")
    if not isinstance(entries, list):
        raise AcpVerifierError("ACP result has no entry list")

    deliveries: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("kind") != "message":
            continue
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict) and decoded.get("condition_key") == key:
            deliveries.append(decoded)
    if len(deliveries) != 1:
        raise AcpVerifierError("ACP result must contain exactly one typed verifier delivery")
    delivery = deliveries[0]
    if delivery.get("source_type") != source_type:
        raise AcpVerifierError("verifier delivery has an unexpected source type")
    value = delivery.get("value")
    if value is None:
        raise AcpVerifierError("verifier delivery has no value")
    address = _address(delivery.get("observer_address"), "verifier observer_address")
    url = _required_string(delivery.get("source_url"), "verifier source_url")
    if not url.startswith(("https://", "http://")):
        raise AcpVerifierError("verifier source_url must be HTTP or HTTPS")
    source_domain = _optional_string(delivery.get("source_domain"), "verifier source_domain")
    if source_domain is not None and source_domain.lower().rstrip(".") != _source_domain(url):
        raise AcpVerifierError("verifier source_domain does not match verifier source_url")
    note = _required_string(delivery.get("note"), "verifier note")
    disclosure = _required_string(delivery.get("disclosure"), "verifier disclosure")
    if disclosure not in note:
        raise AcpVerifierError("verifier disclosure is not present in the signed EAS note")
    value_type_raw = delivery.get("value_type", expected_value_type or "number")
    value_type = _required_string(value_type_raw, "verifier value_type")
    if value_type not in {"number", "boolean", "date", "set"}:
        raise AcpVerifierError("verifier value_type is not supported")
    if expected_value_type is not None and value_type != expected_value_type:
        raise AcpVerifierError("verifier value_type does not match the requested condition")
    unit = _optional_string(delivery.get("unit"), "verifier unit")
    if expected_unit is not None and unit != expected_unit:
        raise AcpVerifierError("verifier unit does not match the requested condition")
    observed_at = _optional_nonnegative_int(delivery.get("observed_at"), "verifier observed_at")
    recorded_at = _optional_nonnegative_int(delivery.get("recorded_at"), "verifier recorded_at")
    if (observed_at is None) != (recorded_at is None):
        raise AcpVerifierError("verifier observed_at and recorded_at must be supplied together")
    if observed_at is None or recorded_at is None:
        raise AcpVerifierError(
            "verifier delivery must include observed_at and recorded_at for bitemporal evidence"
        )
    if recorded_at < observed_at:
        raise AcpVerifierError("verifier recorded_at must not precede observed_at")
    extraction_method = _optional_string(delivery.get("extraction_method"), "verifier extraction_method")
    extraction_version = _optional_string(delivery.get("extraction_version"), "verifier extraction_version")
    evidence_hash_value = _optional_hash(delivery.get("evidence_hash"), "verifier evidence_hash")
    source_snapshot_hash = _optional_hash(
        delivery.get("source_snapshot_hash"),
        "verifier source_snapshot_hash",
    )
    source_publication_date = _optional_nonnegative_int(
        delivery.get("source_publication_date"),
        "verifier source_publication_date",
    )
    ref_uid = _optional_uid(delivery.get("ref_uid"))
    demo_controlled = delivery.get("demo_controlled", False)
    if not isinstance(demo_controlled, bool):
        raise AcpVerifierError("verifier demo_controlled must be true or false")
    return VerifierObservation(
        condition_key=key,
        value=value,
        source_type=source_type,
        source_url=url,
        observation_uid=_uid(delivery.get("observation_uid"), "verifier observation_uid"),
        observer_address=address,
        effective_from=_nonnegative_int(delivery.get("effective_from"), "verifier effective_from"),
        note=note,
        disclosure=disclosure,
        job_id=job_id,
        observation_transaction=_optional_uid(delivery.get("observation_transaction")),
        provenance=_parse_provenance(delivery.get("provenance")),
        value_type=value_type,
        unit=unit,
        observed_at=observed_at,
        recorded_at=recorded_at,
        extraction_method=extraction_method,
        extraction_version=extraction_version,
        evidence_hash=evidence_hash_value,
        source_snapshot_hash=source_snapshot_hash,
        source_publication_date=source_publication_date,
        demo_controlled=demo_controlled,
        ref_uid=ref_uid,
        source_domain=source_domain,
    )


def _parse_provenance(value: Any) -> ObservationProvenance:
    try:
        return ObservationProvenance.from_mapping(value, label="verifier provenance")
    except ProvenanceError as error:
        raise AcpVerifierError(str(error)) from error


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcpVerifierError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, label)


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AcpVerifierError(f"{label} must be a non-negative integer")
    return int(value)


def _optional_hash(value: Any, label: str) -> str | None:
    raw = _optional_string(value, label)
    if raw is None:
        return None
    normalized = raw.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise AcpVerifierError(f"{label} must be a 64-character hexadecimal SHA-256 hash")
    return normalized


def _source_domain(source_url: str) -> str:
    hostname = urlparse(source_url).hostname
    if hostname is None:
        raise AcpVerifierError("verifier source_url has no hostname")
    return hostname.lower().rstrip(".")


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AcpVerifierError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AcpVerifierError(f"{label} must be a non-negative integer")
    return value


def _positive_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise AcpVerifierError(f"{label} must be a positive number")
    return float(value)


def _nonnegative_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise AcpVerifierError(f"{label} must be a non-negative number")
    return float(value)


def _optional_job_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or not value.strip().isdigit():
        raise AcpVerifierError("job_id must be a positive decimal string")
    if int(value.strip()) <= 0:
        raise AcpVerifierError("job_id must be a positive decimal string")
    return value.strip()


def _address(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 42:
        raise AcpVerifierError(f"{label} must be a 20-byte EVM address")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise AcpVerifierError(f"{label} must be a 20-byte EVM address") from error
    return value


def _uid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
        raise AcpVerifierError(f"{label} must be a 32-byte hex value")
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise AcpVerifierError(f"{label} must be a 32-byte hex value") from error
    return value


def _optional_uid(value: Any) -> str | None:
    if value is None:
        return None
    return _uid(value, "verifier observation_transaction")
