"""The Phase 1 memory boundary for Standing.

This module deliberately exposes one client shape for normal and empty-memory
runs. The rest of Standing does not need to know which store it received.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence, cast

from sibyl_memory_client import MemoryClient  # type: ignore[import-untyped]

from .lifecycle import DecisionRevision, Remediation, Waiver
from scripts.sibyl_archive import connect_database, restore_archived


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_MEMORY_PATH = Path(".standing-memory.db")


def _required_name(value: str, label: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError(f"{label} must not be empty")
    return name


@dataclass
class MemoryStore:
    """Typed operations Standing needs from the real Sibyl client."""

    client: MemoryClient
    path: Path
    tenant_id: str
    temporary_directory: TemporaryDirectory[str] | None = None

    def save_decision(self, decision_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Write one decision and return the stored row."""

        name = _required_name(decision_id, "decision_id")
        return cast(dict[str, Any], self.client.set_entity("decision", name, dict(body)))

    def save_decision_revision(
        self,
        revision: DecisionRevision | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one immutable decision revision by its stable revision ID."""

        parsed = revision if isinstance(revision, DecisionRevision) else DecisionRevision.from_mapping(revision)
        return cast(
            dict[str, Any],
            self.client.set_entity("decision_revision", parsed.revision_id, parsed.as_dict()),
        )

    def read_decision_revision(self, revision_id: str) -> dict[str, Any]:
        """Read one immutable decision revision."""

        key = _required_name(revision_id, "revision_id")
        return cast(dict[str, Any], self.client.get_entity("decision_revision", key))

    def list_decision_revisions(self, decision_id: str) -> list[dict[str, Any]]:
        """Read all revisions for one decision in effective-time order."""

        key = _required_name(decision_id, "decision_id")
        rows: list[dict[str, Any]] = []
        for entity in self.client.list_entities(category="decision_revision", limit=10_000):
            body = entity.get("body")
            if not isinstance(body, Mapping):
                raise TypeError("Sibyl returned a decision revision without a mapping body")
            parsed = DecisionRevision.from_mapping(body)
            if parsed.decision_id == key:
                rows.append(dict(entity))
        return sorted(
            rows,
            key=lambda row: (
                int(_entity_body(row).get("effective_from", 0)),
                str(_entity_body(row).get("revision_id", row.get("key", ""))),
            ),
        )

    def read_decision(self, decision_id: str) -> dict[str, Any]:
        """Read one decision through the Sibyl client."""

        name = _required_name(decision_id, "decision_id")
        return cast(dict[str, Any], self.client.get_entity("decision", name))

    def save_condition(self, condition_key: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Write one condition record."""

        key = _required_name(condition_key, "condition_key")
        return cast(dict[str, Any], self.client.set_entity("condition", key, dict(body)))

    def read_condition(self, condition_key: str) -> dict[str, Any]:
        """Read one condition record."""

        key = _required_name(condition_key, "condition_key")
        return cast(dict[str, Any], self.client.get_entity("condition", key))

    def save_observer(self, address: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Write one observer reliability record."""

        observer_address = _required_name(address, "observer address")
        return cast(
            dict[str, Any],
            self.client.set_entity("observer", observer_address, dict(body)),
        )

    def read_observer(self, address: str) -> dict[str, Any]:
        """Read one observer reliability record."""

        observer_address = _required_name(address, "observer address")
        return cast(dict[str, Any], self.client.get_entity("observer", observer_address))

    def save_observation(self, observation_uid: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one checked observation keyed by its immutable EAS UID."""

        uid = _required_name(observation_uid, "observation UID")
        return cast(
            dict[str, Any],
            self.client.set_entity("observation", uid, dict(body)),
        )

    def save_remediation(self, remediation: Remediation | Mapping[str, Any]) -> dict[str, Any]:
        """Persist one remediation record by its stable ID."""

        parsed = remediation if isinstance(remediation, Remediation) else Remediation.from_mapping(remediation)
        return cast(
            dict[str, Any],
            self.client.set_entity("remediation", parsed.remediation_id, parsed.as_dict()),
        )

    def read_remediation(self, remediation_id: str) -> dict[str, Any]:
        """Read one remediation record."""

        key = _required_name(remediation_id, "remediation_id")
        return cast(dict[str, Any], self.client.get_entity("remediation", key))

    def list_remediations(self, decision_id: str) -> list[dict[str, Any]]:
        """Read remediation records for one decision in update-time order."""

        key = _required_name(decision_id, "decision_id")
        rows: list[dict[str, Any]] = []
        for entity in self.client.list_entities(category="remediation", limit=10_000):
            body = entity.get("body")
            if not isinstance(body, Mapping):
                raise TypeError("Sibyl returned a remediation without a mapping body")
            parsed = Remediation.from_mapping(body)
            if parsed.decision_id == key:
                rows.append(dict(entity))
        return sorted(
            rows,
            key=lambda row: (
                int(_entity_body(row).get("updated_at", 0)),
                str(_entity_body(row).get("remediation_id", row.get("key", ""))),
            ),
        )

    def save_waiver(self, waiver: Waiver | Mapping[str, Any]) -> dict[str, Any]:
        """Persist one human-issued waiver by its stable ID."""

        parsed = waiver if isinstance(waiver, Waiver) else Waiver.from_mapping(waiver)
        return cast(
            dict[str, Any],
            self.client.set_entity("waiver", parsed.waiver_id, parsed.as_dict()),
        )

    def read_waiver(self, waiver_id: str) -> dict[str, Any]:
        """Read one waiver record."""

        key = _required_name(waiver_id, "waiver_id")
        return cast(dict[str, Any], self.client.get_entity("waiver", key))

    def list_waivers(self, decision_id: str) -> list[dict[str, Any]]:
        """Read waiver records for one decision in issue-time order."""

        key = _required_name(decision_id, "decision_id")
        rows: list[dict[str, Any]] = []
        for entity in self.client.list_entities(category="waiver", limit=10_000):
            body = entity.get("body")
            if not isinstance(body, Mapping):
                raise TypeError("Sibyl returned a waiver without a mapping body")
            parsed = Waiver.from_mapping(body)
            if parsed.decision_id == key:
                rows.append(dict(entity))
        return sorted(
            rows,
            key=lambda row: (
                int(_entity_body(row).get("issued_at", 0)),
                str(_entity_body(row).get("waiver_id", row.get("key", ""))),
            ),
        )

    def list_observations(self, condition_key: str) -> list[dict[str, Any]]:
        """Read all persisted observations for one condition deterministically."""

        key = _required_name(condition_key, "condition key")
        observations: list[dict[str, Any]] = []
        for entity in self.client.list_entities(category="observation", limit=10_000):
            body = entity.get("body")
            if not isinstance(body, dict):
                raise TypeError("Sibyl returned an observation without a mapping body")
            if body.get("condition_key") == key:
                observations.append(dict(body))
        return sorted(
            observations,
            key=lambda observation: str(observation.get("observation_uid", "")),
        )

    def save_standing(self, decision_id: str, body: Mapping[str, Any]) -> None:
        """Store the hot current-standing state for boot-time reads."""

        name = _required_name(decision_id, "decision_id")
        self.client.set_state(f"standing:{name}", dict(body))

    def read_standing(self, decision_id: str) -> dict[str, Any] | None:
        """Read the current-standing state, if it has not been written yet."""

        name = _required_name(decision_id, "decision_id")
        stored = self.client.get_state(f"standing:{name}")
        if stored is None:
            return None
        body = stored.get("body")
        if not isinstance(body, dict):
            raise TypeError("Sibyl returned standing state without a mapping body")
        return body

    def save_condition_reference(
        self,
        condition_key: str,
        body: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Store the accepted condition value and its evidence pointers."""

        key = _required_name(condition_key, "condition_key")
        reference_metadata = dict(metadata) if metadata is not None else {}
        self.client.set_reference(f"condition:{key}", dict(body), metadata=reference_metadata)

    def read_condition_reference(self, condition_key: str) -> dict[str, Any] | None:
        """Read an accepted condition value and its evidence pointers."""

        key = _required_name(condition_key, "condition_key")
        stored = self.client.get_reference(f"condition:{key}")
        if stored is None:
            return None
        raw_body = stored.get("body")
        if isinstance(raw_body, str):
            decoded_body = json.loads(raw_body)
        else:
            decoded_body = raw_body
        if not isinstance(decoded_body, dict):
            raise TypeError("Sibyl returned a condition reference without a mapping body")
        metadata = stored.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("Sibyl returned condition reference metadata in an invalid shape")
        return {
            "body": decoded_body,
            "metadata": metadata,
            "updated_at": stored.get("updated_at"),
        }

    def record_standing_change(
        self,
        *,
        evaluated: Mapping[str, Any],
        acted: Mapping[str, Any],
        forward: Mapping[str, Any],
        extra: Mapping[str, Any],
        ts: str | None = None,
    ) -> str:
        """Append one standing change to the permanent journal."""

        return cast(
            str,
            self.client.write_event(
                evaluated=dict(evaluated),
                acted=dict(acted),
                forward=dict(forward),
                extra=dict(extra),
                ts=ts,
            ),
        )

    def record_lifecycle_event(
        self,
        *,
        event_type: str,
        decision_id: str,
        acted: Mapping[str, Any],
        forward: Mapping[str, Any],
        extra: Mapping[str, Any] | None = None,
        ts: str | None = None,
    ) -> str:
        """Append a revision, remediation, or waiver event to the same journal."""

        kind = _required_name(event_type, "event_type")
        key = _required_name(decision_id, "decision_id")
        event_extra = {"event_type": kind}
        if extra is not None:
            event_extra.update(dict(extra))
        return cast(
            str,
            self.client.write_event(
                evaluated={"decision_id": key, "event_type": kind},
                acted=dict(acted),
                forward=dict(forward),
                extra=event_extra,
                ts=ts,
            ),
        )

    def read_standing_changes(self) -> list[dict[str, Any]]:
        """Read the permanent standing-change journal for boot-time review."""

        return cast(list[dict[str, Any]], self.client.read_events())

    def search_decisions(self, governed_paths: Sequence[str]) -> list[dict[str, Any]]:
        """Find decisions whose stored governed paths contain any requested path."""

        found: dict[str, dict[str, Any]] = {}
        for path in governed_paths:
            query = _required_name(path, "governed path")
            for result in self.client.search(query):
                if result.get("tier") != "entity" or result.get("category") != "decision":
                    continue
                key = result.get("key")
                if not isinstance(key, str):
                    raise TypeError("Sibyl returned a decision without a string key")
                found[key] = dict(result)
        return list(found.values())

    def archive_decision(self, decision_id: str, *, reason: str) -> dict[str, str]:
        """Move one decision to Sibyl's archive tier."""

        name = _required_name(decision_id, "decision_id")
        result = self.client.archive_entity("decision", name, reason=reason)
        archived_id = result.get("archived_id")
        original_id = result.get("original_id")
        if not isinstance(archived_id, str) or not isinstance(original_id, str):
            raise TypeError("Sibyl returned an invalid archive result")
        return {"archived_id": archived_id, "original_id": original_id}

    def restore_decision(self, archive_id: str) -> dict[str, Any]:
        """Restore one archived decision using the documented SDK fallback."""

        archive_key = _required_name(archive_id, "archive_id")
        connection = connect_database(self.path)
        try:
            restored = restore_archived(connection, self.tenant_id, archive_id=archive_key)
        finally:
            connection.close()
        return self.read_decision(restored.name)

    def close(self) -> None:
        """Close the SDK connection and the temporary empty store, if any."""

        self.client.storage.close()
        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()
            self.temporary_directory = None


def _entity_body(entity: Mapping[str, Any]) -> Mapping[str, Any]:
    body = entity.get("body")
    if not isinstance(body, Mapping):
        raise TypeError("Sibyl returned an entity without a mapping body")
    return body


def create_memory_store(
    *,
    path: str | Path | None = None,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> MemoryStore:
    """Create the real store or a fresh empty store with the same interface."""

    tenant = _required_name(tenant_id, "tenant_id")
    mode = os.environ.get("MEMORY")
    if mode is None:
        mode = "on"
    mode = mode.strip().lower()
    if mode not in {"on", "off"}:
        raise ValueError("MEMORY must be 'on' or 'off'")

    if mode == "off":
        temporary_directory = TemporaryDirectory(prefix="standing-memory-off-")
        database_path = Path(temporary_directory.name) / "memory.db"
        client = MemoryClient.local(database_path, tenant_id=tenant)
        return MemoryStore(client, database_path, tenant, temporary_directory)

    if path is None:
        configured_path = os.environ.get("STANDING_MEMORY_PATH")
        database_path = DEFAULT_MEMORY_PATH if configured_path is None else Path(configured_path)
    else:
        database_path = Path(path)
    database_path = database_path.expanduser()
    client = MemoryClient.local(database_path, tenant_id=tenant)
    return MemoryStore(client, database_path, tenant)
