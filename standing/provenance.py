"""Structured provenance used to bind observations to people, sources, and methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


class ProvenanceError(ValueError):
    """Raised when evidence provenance or source binding is malformed."""


@dataclass(frozen=True)
class ObservationProvenance:
    """The public lineage attached to one observer reading."""

    operator_id: str
    source_id: str
    extractor_id: str
    operator_type: str | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Any,
        *,
        label: str = "observation provenance",
    ) -> ObservationProvenance:
        if not isinstance(raw, Mapping):
            raise ProvenanceError(f"{label} must be an object")
        operator_type = raw.get("operator_type")
        if operator_type is not None:
            operator_type = _required_string(operator_type, f"{label}.operator_type")
        return cls(
            operator_id=_required_string(raw.get("operator_id"), f"{label}.operator_id"),
            source_id=_required_string(raw.get("source_id"), f"{label}.source_id"),
            extractor_id=_required_string(raw.get("extractor_id"), f"{label}.extractor_id"),
            operator_type=operator_type,
        )

    def as_dict(self) -> dict[str, str]:
        """Return a stable JSON-compatible representation."""

        result = {
            "operator_id": self.operator_id,
            "source_id": self.source_id,
            "extractor_id": self.extractor_id,
        }
        if self.operator_type is not None:
            result["operator_type"] = self.operator_type
        return result


@dataclass(frozen=True)
class SourceBinding:
    """The source constraints for a condition's observations."""

    allowed_hosts: tuple[str, ...]
    canonical_url: str | None = None
    publisher_id: str | None = None
    source_type: str | None = None
    value_type: str | None = None
    unit: str | None = None

    @classmethod
    def from_mapping(cls, raw: Any) -> SourceBinding:
        if not isinstance(raw, Mapping):
            raise ProvenanceError("source_binding must be an object")
        raw_hosts = raw.get("allowed_hosts")
        if not isinstance(raw_hosts, Sequence) or isinstance(raw_hosts, (str, bytes)):
            raise ProvenanceError("source_binding.allowed_hosts must be a list")
        hosts = tuple(sorted({_normalize_host(item) for item in raw_hosts}))
        if not hosts:
            raise ProvenanceError("source_binding.allowed_hosts must not be empty")
        canonical_raw = raw.get("canonical_url")
        canonical_url = None
        if canonical_raw is not None:
            canonical_url = _required_url(canonical_raw, "source_binding.canonical_url")
        publisher_raw = raw.get("publisher_id")
        publisher_id = None
        if publisher_raw is not None:
            publisher_id = _required_string(publisher_raw, "source_binding.publisher_id")
        source_type_raw = raw.get("source_type")
        source_type = None
        if source_type_raw is not None:
            source_type = _required_string(source_type_raw, "source_binding.source_type")
        value_type_raw = raw.get("value_type")
        value_type = None
        if value_type_raw is not None:
            value_type = _required_string(value_type_raw, "source_binding.value_type")
        unit_raw = raw.get("unit")
        unit = None
        if unit_raw is not None:
            unit = _required_string(unit_raw, "source_binding.unit").lower()
        return cls(hosts, canonical_url, publisher_id, source_type, value_type, unit)

    def allows(self, url: str, *, require_canonical: bool = False) -> bool:
        """Return whether a URL is within the configured source boundary."""

        normalized_url = _required_url(url, "source URL")
        host = _normalize_host(urlparse(normalized_url).hostname)
        host_allowed = host in self.allowed_hosts
        if not host_allowed:
            return False
        if require_canonical and self.canonical_url is not None:
            return normalized_url.rstrip("/") == self.canonical_url.rstrip("/")
        return True


def _required_url(value: Any, label: str) -> str:
    url = _required_string(value, label)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ProvenanceError(f"{label} must be an HTTP or HTTPS URL")
    return url


def _normalize_host(value: Any) -> str:
    host = _required_string(value, "source host").lower().rstrip(".")
    if "." not in host and host not in {"localhost"}:
        raise ProvenanceError("source host must be a hostname")
    return host


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceError(f"{label} must be a non-empty string")
    return value.strip()
