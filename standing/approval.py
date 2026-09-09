"""Explicit human approval records bound to the exact evidence set."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ManualApprovalError(ValueError):
    """Raised when an approval is not human-issued or does not match evidence."""


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManualApprovalError(f"{label} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ManualApprovalError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ManualApproval:
    """A human approval tied to one condition and one exact evidence digest."""

    approval_id: str
    condition_key: str
    approved_by: str
    approver_role: str
    approved_at: int
    evidence_fingerprint: str
    reason: str

    def __post_init__(self) -> None:
        _required_string(self.approval_id, "approval_id")
        _required_string(self.condition_key, "condition_key")
        _required_string(self.approved_by, "approved_by")
        if not isinstance(self.approver_role, str) or self.approver_role.strip().lower() != "human":
            raise ManualApprovalError("only a human may issue manual approval")
        _nonnegative_int(self.approved_at, "approved_at")
        fingerprint = _required_string(self.evidence_fingerprint, "evidence_fingerprint")
        if len(fingerprint) != 64:
            raise ManualApprovalError("evidence_fingerprint must be a SHA-256 digest")
        try:
            int(fingerprint, 16)
        except ValueError as error:
            raise ManualApprovalError("evidence_fingerprint must be a SHA-256 digest") from error
        _required_string(self.reason, "reason")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ManualApproval:
        if not isinstance(raw, Mapping):
            raise ManualApprovalError("manual approval must be a mapping")
        return cls(
            _required_string(raw.get("approval_id"), "approval_id"),
            _required_string(raw.get("condition_key"), "condition_key"),
            _required_string(raw.get("approved_by"), "approved_by"),
            _required_string(raw.get("approver_role"), "approver_role"),
            _nonnegative_int(raw.get("approved_at"), "approved_at"),
            _required_string(raw.get("evidence_fingerprint"), "evidence_fingerprint"),
            _required_string(raw.get("reason"), "reason"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "condition_key": self.condition_key,
            "approved_by": self.approved_by,
            "approver_role": self.approver_role,
            "approved_at": self.approved_at,
            "evidence_fingerprint": self.evidence_fingerprint,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ApprovalCheck:
    """Whether a manual approval authorizes the supplied evidence."""

    valid: bool
    approval_id: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "approval_id": self.approval_id, "reason": self.reason}


def evidence_fingerprint(
    condition_key: str,
    observations: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the complete evidence set so approval cannot drift silently."""

    key = _required_string(condition_key, "condition_key")
    normalized: list[Any] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise ManualApprovalError("each observation must be a mapping")
        normalized.append(_stable_value(dict(observation)))
    normalized.sort(key=_canonical_json)
    payload = json.dumps(
        {"condition_key": key, "observations": normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def issue_manual_approval(
    approval_id: str,
    condition_key: str,
    *,
    approved_by: str,
    approver_role: str,
    approved_at: int,
    evidence_digest: str,
    reason: str,
) -> ManualApproval:
    """Create an approval only after a human identity and reason are supplied."""

    return ManualApproval(
        _required_string(approval_id, "approval_id"),
        _required_string(condition_key, "condition_key"),
        _required_string(approved_by, "approved_by"),
        _required_string(approver_role, "approver_role"),
        _nonnegative_int(approved_at, "approved_at"),
        _required_string(evidence_digest, "evidence_digest"),
        _required_string(reason, "reason"),
    )


def check_manual_approval(
    approval: ManualApproval | None,
    *,
    condition_key: str,
    evidence_digest: str,
) -> ApprovalCheck:
    """Check the approval binding without changing the acceptance result."""

    key = _required_string(condition_key, "condition_key")
    digest = _required_string(evidence_digest, "evidence_digest")
    if approval is None:
        return ApprovalCheck(False, None, "No explicit human approval record is present.")
    if approval.condition_key != key:
        return ApprovalCheck(False, approval.approval_id, "The approval covers a different condition.")
    if approval.evidence_fingerprint.lower() != digest.lower():
        return ApprovalCheck(False, approval.approval_id, "The approval is bound to a different evidence set.")
    return ApprovalCheck(True, approval.approval_id, "The explicit human approval matches the evidence.")


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
    raise ManualApprovalError(f"value of type {type(value).__name__} cannot be fingerprinted")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
