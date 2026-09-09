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

    @classmethod
    def from_mapping(
        cls,
        raw: Any,
        *,
        label: str = "observation provenance",
    ) -> ObservationProvenance:
        if not isinstance(raw, Mapping):
            raise ProvenanceError(f"{label} must be an object")
        return cls(
            operator_id=_required_string(raw.get("operator_id"), f"{label}.operator_id"),
            source_id=_required_string(raw.get("source_id"), f"{label}.source_id"),
            extractor_id=_required_string(raw.get("extractor_id"), f"{label}.extractor_id"),
        )

    def as_dict(self) -> dict[str, str]:
        """Return a stable JSON-compatible representation."""

        return {
            "operator_id": self.operator_id,
            "source_id": self.source_id,
            "extractor_id": self.extractor_id,
        }


@dataclass(frozen=True)
class SourceBinding:
    """The source constraints for a condition's observations."""

    allowed_hosts: tuple[str, ...]
    canonical_url: str | None = None
    publisher_id: str | None = None

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
        return cls(hosts, canonical_url, publisher_id)

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
