"""Standing Console and controlled-scenario application."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

from .memory import MemoryStore, create_memory_store
from .model_review import DecisionProposal
from .reviewer import ReviewerToolError, ReviewerTools
from .temporal import TemporalObservationError, observation_evidence_hash, parse_timestamp


CONTROLLED_DISCLOSURE = (
    "CONTROLLED SCENARIO — FICTIONAL ACME. "
    "This sandbox uses fictional Acme data operated by Standing so the lifecycle "
    "can be reproduced safely. The control below replays the source change locally. "
    "Completed Virtuals ACP → source extraction → Base EAS records are shown separately "
    "as live historical proof."
)
SANDBOX_CONDITION = "sandbox.acme.retention_days"
SANDBOX_PATH = "src/archive.py"
SANDBOX_SOURCE_URL = "https://raw.githubusercontent.com/Jennycruzy/standing/main/docs/sandbox/acme-retention.json"
SANDBOX_PROPOSAL_ARTIFACT = "docs/decisions/0001-acp-adapter.md"
SANDBOX_DECISION_DATE = parse_timestamp("2026-02-11", label="sandbox decision date")
SANDBOX_EFFECTIVE_INITIAL = 1767225600  # 2026-01-01T00:00:00Z
SANDBOX_EFFECTIVE_CHANGED = 1788739200  # 2026-09-07T00:00:00Z
_SOURCE_CASES_PATH = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "cases.json"
_WORKTREE_CASES_PATH = Path.cwd() / "docs" / "evaluation" / "cases.json"
EVALUATION_CASES_PATH = (
    _SOURCE_CASES_PATH if _SOURCE_CASES_PATH.exists() else _WORKTREE_CASES_PATH
)
PARTNER_PROOF = {
    "acp_job_id": "77748",
    "acp_job_url": "https://api.acp.virtuals.io/jobs/8453/77748",
    "acp_public_url": "https://app.virtuals.io/",
    "eas_uid": "0x70675af1277c400c155de2e32684cfb264be8061578fb9afa17c6fcdd001bf5e",
    "eas_transaction_url": "https://basescan.org/tx/0xfa23b10158da3723d28508d51c8acd6916696cd0a609e4fce741c989e5573eff",
    "erc8004_transaction_url": "https://basescan.org/tx/0xb12f670d1c643556b7bb6c45cec12462f9c7f7e41775681b4c1f9b0278146954",
    "acp_directory_url": "https://app.virtuals.io/acp/agents",
    "acp_scan_url": "https://app.virtuals.io/acp/scan",
    "agents": [
        {"name": "Standing Verifier", "role": "HYBRID · verifier", "virtual_agent_id": "139452"},
        {"name": "Standing Requestor", "role": "HYBRID · requestor", "virtual_agent_id": "139450"},
    ],
    "erc8004_agent_id": "84973",
    "erc8004_identity_url": "https://basescan.org/tx/0xb1a5586929a8b02fb6a4527551124ce290328eda684aa18a424a78e2de64e733",
    "summary": "Completed ACP verification → Base EAS observation → Sibyl update → ERC-8004 feedback",
}


@dataclass
class SandboxController:
    """A fixed, local-only controller for the public sandbox buttons."""

    store: MemoryStore
    tools: ReviewerTools

    @classmethod
    def create(cls, store: MemoryStore) -> SandboxController:
        controller = cls(store, ReviewerTools(store))
        controller.seed()
        return controller

    def seed(self) -> None:
        """Create the pre-authored initial sandbox state in the supplied store."""

        try:
            self.store.read_decision("ACME-001")
            return
        except NotFoundError:
            pass
        self.store.save_decision(
            "ACME-001",
            {
                "decision_id": "ACME-001",
                "title": "Use Acme for event archives",
                "description": "Use Acme because its retention guarantee meets the archive requirement.",
                "recorded_at": "2026-02-11",
                "effective_from": "2026-02-11",
                "status": "CURRENT",
                "author": "alice",
                "approver": "bob",
                "governed_paths": [SANDBOX_PATH, "infra/acme.tf"],
                "conditions": [
                    {
                        "condition_key": SANDBOX_CONDITION,
                        "predicate": "retention_days >= 365",
                        "provenance": "CONFIRMED",
                        "required": True,
                    }
                ],
            },
        )
        initial = _sandbox_observation(
            "sandbox-initial",
            365,
            SANDBOX_EFFECTIVE_INITIAL,
            "2026-02-11",
        )
        self.tools.record_temporal_observation(initial)
        self._save_sandbox_reference(initial)
        evaluation = self.tools.evaluate_standing("ACME-001")
        self.tools.write_standing_change(
            "ACME-001",
            evaluation,
            action="allow",
            explanation="Initial controlled sandbox decision was human-approved.",
        )
        self.tools.record_decision_proposal(
            DecisionProposal(
                decision_id="AUDIT-003",
                title="Keep an audit trail for archive changes",
                description="A non-blocking proposal retained to shows confirmation workflow.",
                governed_paths=("docs/audits/",),
                conditions=(
                    {
                        "condition_key": "vendor.audit.logging",
                        "predicate": "supports_sso == true",
                        "required": False,
                        "provenance": "INFERRED",
                        "unit": None,
                    },
                ),
                artifact_path=SANDBOX_PROPOSAL_ARTIFACT,
                artifact_type="DESIGN_DOCUMENT",
                artifact_sha256="d" * 64,
                source_sentence="A controlled pending proposal shows human confirmation.",
                rationale="This fixed proposal is informational and cannot block until a human confirms it.",
                model_id="standing-model",
            )
        )

    def break_assumption(self) -> None:
        self._ensure_decision()
        observation = _sandbox_observation("sandbox-changed", 90, SANDBOX_EFFECTIVE_CHANGED, "2026-09-09")
        if not any(item.get("observation_uid") == observation["observation_uid"] for item in self.tools.read_observations(SANDBOX_CONDITION)):
            self.tools.record_temporal_observation(observation)
        self._save_sandbox_reference(observation)
        evaluation = self.tools.evaluate_standing("ACME-001")
        if evaluation.state.value != "STANDS":
            self.tools.write_standing_change(
                "ACME-001",
                evaluation,
                action="block",
                explanation="The fixed controlled source changed from 365 to 90 days.",
            )

    def reset(self) -> None:
        """Return the sandbox to its initial state without deleting history."""

        self._ensure_decision()
        try:
            current = self.store.read_decision("ACME-001")
            body = _entity_body(current)
            if body.get("status") == "SUPERSEDED":
                for field in ("superseded_at", "superseded_by", "supersession_reason", "superseded_by_actor", "supersession_recorded_at"):
                    body.pop(field, None)
                body["status"] = "CURRENT"
                self.store.save_decision("ACME-001", body)
        except NotFoundError as error:
            raise ReviewerToolError("controlled sandbox decision is not available") from error
        try:
            self.store.archive_decision("STORAGE-002", reason="sandbox reset; replacement retained in archive")
        except (NotFoundError, RuntimeError, ValueError):
            pass
        observation = _sandbox_observation(
            "sandbox-reset",
            365,
            int(time()),
            "2026-09-10",
            ref_uid="sandbox-changed",
        )
        self.tools.record_temporal_observation(observation)
        self._save_sandbox_reference(observation)
        evaluation = self.tools.evaluate_standing("ACME-001")
        self.tools.write_standing_change(
            "ACME-001",
            evaluation,
            action="allow",
            explanation="The sandbox was reset to the initial 365-day source state.",
        )

    def resolve(self) -> None:
        self._ensure_decision()
        try:
            self.store.read_decision("STORAGE-002")
            return
        except NotFoundError:
            pass
        self.tools.record_replacement_decision(
            "ACME-001",
            "STORAGE-002",
            {
                "title": "Move archive storage to Contoso",
                "description": "Replacement decision for the expired Acme archive assumption.",
                "author": "alice",
                "approver": "bob",
                "governed_paths": [SANDBOX_PATH, "infra/contoso.tf"],
                "conditions": [
                    {
                        "condition_key": "vendor.contoso.archive_supported",
                        "predicate": "supports_sso == true",
                        "provenance": "CONFIRMED",
                        "required": True,
                    }
                ],
            },
            actor_id="alice",
            reason="The old Acme retention assumption expired; Contoso is the approved replacement.",
            effective_from=int(time()),
            recorded_at=int(time()),
        )
        self.store.save_condition_reference(
            "vendor.contoso.archive_supported",
            {
                "condition_key": "vendor.contoso.archive_supported",
                "accepted_value": True,
                "value_type": "boolean",
                "unit": "boolean",
                "accepted_source_url": SANDBOX_SOURCE_URL,
                "observation_uids": ["controlled-contoso-sandbox"],
                "basis": "fixed replacement decision in the sandbox",
                "evidence_fresh": True,
            },
        )
        evaluation = self.tools.evaluate_standing("STORAGE-002")
        self.tools.write_standing_change(
            "STORAGE-002",
            evaluation,
            action="allow",
            explanation="Replacement decision is now the active governing decision.",
        )

    def confirm_proposal(self) -> None:
        proposal = self._pending_sandbox_proposal()
        self.tools.confirm_decision_proposal(
            proposal,
            confirmed_by="sandbox-human",
            confirmation_note="Human reviewed the displayed source sentence and confirmed this proposal.",
            confirmed_at=int(time()),
        )

    def reject_proposal(self) -> None:
        proposal = self._pending_sandbox_proposal()
        self.tools.reject_decision_proposal(
            proposal,
            rejected_by="sandbox-human",
            reason="Human rejected the displayed proposal for this sandbox run.",
            rejected_at=int(time()),
        )

    def waiver_preview(self) -> dict[str, Any]:
        return {
            "status": "PREVIEW ONLY",
            "disclosure": "No waiver is issued by this sandbox action.",
            "decision_id": "ACME-001",
            "approved_by": "human approval required",
            "reason": "production incident mitigation",
            "expires_at": int(time()) + 86_400,
            "automatic_block_restoration": True,
        }

    def _ensure_decision(self) -> None:
        try:
            self.store.read_decision("ACME-001")
        except NotFoundError as error:
            raise ReviewerToolError("controlled sandbox decision is not available") from error

    def _pending_sandbox_proposal(self) -> str:
        for entity in self.store.list_decision_proposals():
            body = _entity_body(entity)
            if body.get("status") == "PENDING":
                proposal_id = entity.get("key", entity.get("name"))
                if isinstance(proposal_id, str) and proposal_id.strip():
                    return proposal_id
        raise ReviewerToolError("no pending controlled sandbox proposal is available")

    def _save_sandbox_reference(self, observation: Mapping[str, Any]) -> None:
        self.store.save_condition_reference(
            SANDBOX_CONDITION,
            {
                "condition_key": SANDBOX_CONDITION,
                "accepted_value": observation["value"],
                "value_type": "number",
                "unit": "days",
                "effective_from": observation["effective_from"],
                "accepted_at": observation["recorded_at"],
                "last_verified_at": observation["recorded_at"],
                "accepted_source_url": SANDBOX_SOURCE_URL,
                "observation_uids": [observation["observation_uid"]],
                "basis": "controlled sandbox source extraction",
                "status": "ACCEPTED",
                "evidence_fresh": True,
                "controlled_scenario": True,
            },
            metadata={"controlled_scenario": True, "source_url": SANDBOX_SOURCE_URL},
        )


class DashboardApp:
    """Small HTTP application used by the local dashboard command."""

    def __init__(self, store: MemoryStore, *, sandbox: bool) -> None:
        self.store = store
        self.tools = ReviewerTools(store)
        self.sandbox = sandbox
        self.controller = SandboxController.create(store) if sandbox else None

    def state(self) -> dict[str, Any]:
        return build_dashboard_payload(self.tools, sandbox=self.sandbox)

    def review(self, paths: Sequence[str] = (SANDBOX_PATH,)) -> dict[str, Any]:
        """Run the deterministic reviewer for the requested changed paths."""

        if not paths:
            raise ReviewerToolError("at least one changed path is required")
        reviews = self.tools.review_paths(paths)
        return _review_payload(paths, reviews)

    def memory_comparison(self) -> dict[str, Any]:
        """Run the same review with the remembered decision and a fresh store."""

        if not self.sandbox:
            raise ReviewerToolError("memory comparison is available only in sandbox mode")
        source = self.source()
        paths = (SANDBOX_PATH,)
        memory_on = self.review(paths)
        with TemporaryDirectory(prefix="standing-memory-removed-") as directory:
            removed_store = create_memory_store(
                path=Path(directory) / "memory.db",
                tenant_id=f"{self.store.tenant_id}:removed",
            )
            try:
                removed_reviews = ReviewerTools(removed_store).review_paths(paths)
                memory_removed = _review_payload(paths, removed_reviews)
            finally:
                removed_store.close()

        return {
            "memory_on": _memory_view(memory_on, source["retention_days"], memory_present=True),
            "memory_removed": _memory_view(memory_removed, source["retention_days"], memory_present=False),
            "same_changed_paths": list(paths),
            "conclusion": "The external fact survives; the remembered engineering reason connecting it to code does not.",
        }

    def source(self) -> dict[str, Any]:
        payload = self.state()
        sandbox = payload["sandbox"]
        if not isinstance(sandbox, dict):
            raise ReviewerToolError("dashboard sandbox payload is invalid")
        return {
            "vendor": "Fictional Acme Corporation",
            "condition_key": SANDBOX_CONDITION,
            "retention_days": sandbox["current_value"],
            "disclosure": CONTROLLED_DISCLOSURE,
            "controlled_scenario": True,
        }

    def action(self, name: str) -> dict[str, Any]:
        if not self.sandbox or self.controller is None:
            raise ReviewerToolError("sandbox actions are disabled outside --sandbox mode")
        if name == "break":
            self.controller.break_assumption()
        elif name == "reset":
            self.controller.reset()
        elif name == "resolve":
            self.controller.resolve()
        elif name == "confirm-proposal":
            self.controller.confirm_proposal()
        elif name == "reject-proposal":
            self.controller.reject_proposal()
        elif name == "waiver":
            return self.controller.waiver_preview()
        elif name == "review":
            payload = self.state()
            payload["review_result"] = self.review()
            return payload
        elif name == "memory-comparison":
            payload = self.state()
            payload["memory_comparison"] = self.memory_comparison()
            return payload
        else:
            raise ReviewerToolError("unknown fixed dashboard action")
        return self.state()


def _review_payload(paths: Sequence[str], reviews: Sequence[Any]) -> dict[str, Any]:
    """Serialize reviewer output for the console and product APIs."""

    serialized: list[dict[str, Any]] = []
    for item in reviews:
        serialized.append(
            {
                "decision_id": item.decision_id,
                "state": item.evaluation.state.value,
                "blocks": item.blocks,
                "action": "BLOCK" if item.blocks else "ALLOW",
                "evaluation": item.evaluation.as_dict(),
            }
        )
    blocked = any(bool(item["blocks"]) for item in serialized)
    first = serialized[0] if serialized else {}
    return {
        "changed_paths": list(paths),
        "decisions_found": len(serialized),
        "decision_id": first.get("decision_id"),
        "state": first.get("state", "UNKNOWN"),
        "blocks": blocked,
        "action": "BLOCK" if blocked else "ALLOW",
        "decisions": serialized,
    }


def _memory_view(review: Mapping[str, Any], current_fact: Any, *, memory_present: bool) -> dict[str, Any]:
    """Project an actual backend review into the Memory Proof comparison."""

    decisions = review.get("decisions")
    first = decisions[0] if isinstance(decisions, Sequence) and decisions else {}
    evaluation = first.get("evaluation") if isinstance(first, Mapping) else {}
    conditions = evaluation.get("conditions", []) if isinstance(evaluation, Mapping) else []
    condition = conditions[0] if isinstance(conditions, Sequence) and conditions else {}
    decision_id = review.get("decision_id")
    has_decision = isinstance(decision_id, str) and bool(decision_id)
    return {
        "decision_found": decision_id if has_decision else None,
        "assumption": condition.get("predicate") if isinstance(condition, Mapping) else None,
        "current_fact": current_fact,
        "expiry_detected": bool(review.get("blocks")) if has_decision else False,
        "protection": (
            review.get("action", "ALLOW")
            if memory_present or has_decision
            else "HISTORICAL PROTECTION UNAVAILABLE"
        ),
    }


def build_dashboard_payload(tools: ReviewerTools, *, sandbox: bool = False) -> dict[str, Any]:
    """Build the product-centered JSON model used by the dashboard."""

    decision_payloads: list[dict[str, Any]] = []
    all_conditions: dict[str, dict[str, Any]] = {}
    for entity in tools.memory.list_decisions():
        decision_id = entity.get("key", entity.get("name"))
        if not isinstance(decision_id, str):
            continue
        body = _entity_body(entity)
        try:
            evaluation = tools.evaluate_standing(decision_id)
        except (ReviewerToolError, ValueError) as error:
            decision_payloads.append({"decision_id": decision_id, "body": body, "error": str(error)})
            continue
        conditions: list[dict[str, Any]] = []
        raw_conditions = body.get("conditions", [])
        if isinstance(raw_conditions, Sequence) and not isinstance(raw_conditions, (str, bytes)):
            for raw_condition in raw_conditions:
                if not isinstance(raw_condition, Mapping):
                    continue
                condition_key = raw_condition.get("condition_key")
                if not isinstance(condition_key, str):
                    continue
                try:
                    reference = tools.current_condition_reference(condition_key)
                except ReviewerToolError:
                    reference = None
                raw_observations = list(tools.read_observations(condition_key))
                temporal_rows: list[dict[str, Any]] = []
                try:
                    temporal_rows = [item.as_dict() for item in tools.condition_history(condition_key)]
                except ReviewerToolError:
                    temporal_rows = raw_observations
                condition_payload = {
                    "condition_key": condition_key,
                    "rule": dict(raw_condition),
                    "reference": reference,
                    "observations": temporal_rows,
                }
                conditions.append(condition_payload)
                all_conditions[condition_key] = condition_payload
        decision_payloads.append(
            {
                "decision_id": decision_id,
                "body": body,
                "evaluation": evaluation.as_dict(),
                "conditions": conditions,
                "active": body.get("status", "CURRENT") not in {"SUPERSEDED", "ARCHIVED"},
            }
        )

    active = [item for item in decision_payloads if item.get("active", True)]
    proposals: list[dict[str, Any]] = []
    for entity in tools.memory.list_decision_proposals():
        proposal_id = entity.get("key", entity.get("name"))
        if not isinstance(proposal_id, str):
            continue
        proposal = _entity_body(entity)
        proposal["proposal_id"] = proposal_id
        proposals.append(proposal)
    findings = [
        item
        for item in active
        if isinstance(item.get("evaluation"), Mapping)
        and item["evaluation"].get("state") != "STANDS"
        and any(bool(condition.get("blocks")) for condition in item["evaluation"].get("conditions", []))
    ]
    primary = findings[0] if findings else (active[0] if active else None)
    sandbox_conditions = all_conditions.get(SANDBOX_CONDITION, {})
    current_value = 365
    if isinstance(sandbox_conditions, Mapping):
        reference = sandbox_conditions.get("reference")
        if isinstance(reference, Mapping) and isinstance(reference.get("accepted_value"), int):
            current_value = reference["accepted_value"]
    now_unix = int(time())
    waivers: list[dict[str, Any]] = []
    for entity in tools.memory.list_all_waivers():
        body = _entity_body(entity)
        waiver_id = entity.get("key", entity.get("name"))
        if not isinstance(waiver_id, str):
            continue
        row = dict(body)
        row["waiver_id"] = waiver_id
        issued_at = row.get("issued_at")
        expires_at = row.get("expires_at")
        row["status"] = (
            "ACTIVE"
            if isinstance(issued_at, int) and isinstance(expires_at, int)
            and issued_at <= now_unix < expires_at
            else "EXPIRED"
        )
        waivers.append(row)
    real_world = _real_world_payload()
    activity = _activity_payload(tools)
    time_travel = _time_travel_payload(tools, sandbox=sandbox)
    return {
        "controlled_scenario": sandbox,
        "disclosure": CONTROLLED_DISCLOSURE if sandbox else None,
        "summary": (
            f"{len(findings)} engineering decision(s) no longer have standing."
            if findings
            else "All remembered engineering decisions currently have standing."
        ),
        "primary_finding": primary,
        "decisions": decision_payloads,
        "proposals": proposals,
        "waivers": waivers,
        "activity": activity,
        "real_world": real_world,
        "evaluation": _evaluation_payload(real_world),
        "partner_proof": dict(PARTNER_PROOF),
        "sandbox": {
            "condition_key": SANDBOX_CONDITION,
            "source_url": SANDBOX_SOURCE_URL,
            "current_value": current_value,
            "initial_value": 365,
            "changed_value": 90,
            "disclosure": CONTROLLED_DISCLOSURE,
            "timeline": {
                "decision_date": SANDBOX_EFFECTIVE_INITIAL,
                "change_date": SANDBOX_EFFECTIVE_CHANGED,
                "now": int(time()),
            },
            "time_travel": time_travel,
        },
        "review_result": _review_payload(
            [SANDBOX_PATH],
            tools.review_paths([SANDBOX_PATH]) if sandbox else (),
        ),
    }


def _time_travel_payload(tools: ReviewerTools, *, sandbox: bool) -> list[dict[str, Any]]:
    """Return backend-resolved bitemporal points for the console slider.

    The browser may select a point in this already-resolved sequence, but it
    must not reconstruct valid-time or knowledge-time answers from raw rows.
    This keeps the console presentation layer from becoming a second temporal
    resolver with subtly different semantics.
    """

    if not sandbox:
        return []
    points_set = {
        SANDBOX_EFFECTIVE_INITIAL,
        SANDBOX_DECISION_DATE,
        SANDBOX_EFFECTIVE_CHANGED,
        int(time()),
    }
    for raw_observation in tools.read_observations(SANDBOX_CONDITION):
        effective_from = raw_observation.get("effective_from")
        if isinstance(effective_from, int):
            points_set.add(effective_from)
    points = sorted(points_set)
    result: list[dict[str, Any]] = []
    for point in points:
        try:
            valid = tools.condition_valid_as_of(
                SANDBOX_CONDITION,
                point,
                accepted_only=True,
            )
            known = tools.condition_known_as_of(
                SANDBOX_CONDITION,
                point,
                valid_at=point,
                accepted_only=True,
            )
        except ReviewerToolError as error:
            result.append(
                {
                    "point": point,
                    "valid": None,
                    "known": None,
                    "assessment": f"Temporal answer unavailable: {error}",
                }
            )
            continue

        valid_record = None if valid is None else valid.as_dict()
        known_record = None if known is None else known.as_dict()
        if valid_record is None and known_record is None:
            assessment = "No evidence was recorded for this point."
        elif valid_record is not None and known_record is not None:
            if valid_record.get("value") == known_record.get("value"):
                assessment = "Evidence and Standing's knowledge align at this point."
            else:
                assessment = (
                    "The decision was justified by the evidence available then; "
                    "later evidence changed the reconstructed world state."
                )
        else:
            assessment = "The outside-world answer and the knowledge answer differ."
        result.append(
            {
                "point": point,
                "valid": valid_record,
                "known": known_record,
                "assessment": assessment,
            }
        )
    return result


def _real_world_payload() -> dict[str, Any]:
    """Expose the real-case release state without turning a candidate into proof."""

    try:
        raw = json.loads(EVALUATION_CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "UNAVAILABLE",
            "reviewed_case_count": 0,
            "pending_case_count": 0,
            "cases": [],
            "disclosure": "The source-linked evaluation manifest could not be read.",
        }
    raw_cases = raw.get("cases") if isinstance(raw, Mapping) else None
    if not isinstance(raw_cases, list):
        return {
            "status": "UNAVAILABLE",
            "reviewed_case_count": 0,
            "pending_case_count": 0,
            "cases": [],
            "disclosure": "The source-linked evaluation manifest has no case list.",
        }
    cases: list[dict[str, Any]] = []
    reviewed = 0
    pending = 0
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping) or raw_case.get("synthetic") is True:
            continue
        human_reviewed = raw_case.get("human_reviewed") is True
        if human_reviewed:
            reviewed += 1
        else:
            pending += 1
        cases.append(
            {
                "case_id": raw_case.get("case_id", "unknown"),
                "repository": raw_case.get("repository", ""),
                "decision_url": raw_case.get("decision_url", ""),
                "historical_ground_truth_url": raw_case.get("historical_ground_truth_url", ""),
                "current_ground_truth_url": raw_case.get("current_ground_truth_url", ""),
                "review_status": "HUMAN REVIEWED" if human_reviewed else "PENDING HUMAN REVIEW",
                "disclosure": (
                    "Counts toward release evidence only after independent human review."
                    if not human_reviewed
                    else "Human review metadata is recorded in the case manifest."
                ),
            }
        )
    return {
        "status": "HUMAN REVIEW REQUIRED" if pending else ("REVIEWED" if reviewed else "NO CASES"),
        "reviewed_case_count": reviewed,
        "pending_case_count": pending,
        "cases": cases,
        "disclosure": (
            "Three human-reviewed public cases are recorded separately from the controlled scenario."
            if reviewed and not pending
            else "Real-world and controlled evidence are kept separate; pending candidates are not product claims."
        ),
    }


def _evaluation_payload(real_world: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the evaluation split without inventing unrun benchmark scores."""

    controlled_path = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "adversarial.json"
    controlled_count = 0
    try:
        raw = json.loads(controlled_path.read_text(encoding="utf-8"))
        raw_cases = raw.get("cases") if isinstance(raw, Mapping) else None
        if isinstance(raw_cases, list):
            controlled_count = len(raw_cases)
    except (OSError, json.JSONDecodeError):
        controlled_count = 0
    return {
        "status": "METRICS NOT PUBLISHED",
        "real_world_cases": real_world.get("reviewed_case_count", 0),
        "controlled_scenarios": controlled_count,
        "arms": ["standing", "no-memory", "grep", "stateless-model", "current-docs-only"],
        "message": "Prediction artifacts are not included, so no benchmark score is claimed.",
        "methodology_url": "https://github.com/Jennycruzy/standing/blob/main/docs/EVALUATION.md",
    }


def _activity_payload(tools: ReviewerTools) -> list[dict[str, Any]]:
    """Turn the Sibyl journal into a compact, human-readable activity feed."""

    rows: list[dict[str, Any]] = []
    for event in tools.memory.read_standing_changes()[-24:]:
        if not isinstance(event, Mapping):
            continue
        extra = event.get("extra")
        extra_map = extra if isinstance(extra, Mapping) else {}
        event_type = extra_map.get("event_type") or event.get("event_type") or "journal event"
        acted = event.get("acted")
        acted_map = acted if isinstance(acted, Mapping) else {}
        explanation = acted_map.get("explanation") or event.get("explanation") or "Recorded in Sibyl Memory."
        evaluated = event.get("evaluated")
        evaluated_map = evaluated if isinstance(evaluated, Mapping) else {}
        decision_id = evaluated_map.get("decision_id") or event.get("decision_id") or "Standing"
        timestamp = event.get("ts") or event.get("timestamp") or event.get("created_at") or ""
        rows.append(
            {
                "timestamp": str(timestamp),
                "event": str(event_type).replace("_", " "),
                "decision_id": str(decision_id),
                "detail": str(explanation),
            }
        )
    return rows


def render_landing_html(payload: Mapping[str, Any], *, page_title: str = "Standing — engineering intent") -> str:
    """Render the public product introduction for the deployed service."""

    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = escape(page_title, quote=True)
    finding = payload.get("primary_finding")
    state = "UNKNOWN"
    decision_id = "—"
    title_text = "The reasoning behind every change."
    current = "—"
    required = "—"
    if isinstance(finding, Mapping):
        decision_id = str(finding.get("decision_id", "—"))
        body = finding.get("body")
        evaluation = finding.get("evaluation")
        if isinstance(body, Mapping):
            title_text = str(body.get("title", title_text))
        if isinstance(evaluation, Mapping):
            state = str(evaluation.get("state", state))
            conditions = evaluation.get("conditions")
            if isinstance(conditions, Sequence) and conditions:
                condition = conditions[0]
                if isinstance(condition, Mapping):
                    current = str(condition.get("accepted_value", "unknown"))
                    required = str(condition.get("predicate", required))
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: dark; --ink:#0b0e0d; --ink-2:#111715; --paper:#e9e2d5; --muted:#9aa49c; --line:#2a342f; --mint:#8ee7bd; --copper:#d69a67; --rose:#ef7890; font-family:Inter,ui-sans-serif,system-ui,sans-serif; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; min-height:100vh; color:var(--paper); background:var(--ink); overflow-x:hidden; }}
    body::before {{ content:""; position:fixed; inset:-30%; pointer-events:none; background:radial-gradient(ellipse at 75% 12%,rgba(90,157,126,.18),transparent 28%),radial-gradient(ellipse at 20% 82%,rgba(146,83,53,.1),transparent 24%); filter:blur(20px); }}
    .wrap {{ position:relative; max-width:1240px; margin:auto; padding:0 30px; }}
    nav {{ position:relative; z-index:2; border-bottom:1px solid var(--line); }} .nav-in {{ min-height:76px; display:flex; align-items:center; gap:24px; }}
    .brand {{ color:var(--paper); font:600 1.22rem Georgia,serif; letter-spacing:.02em; }} .brand span {{ color:var(--mint); }} .nav-links {{ margin-left:auto; display:flex; gap:26px; align-items:center; }} .nav-links a {{ color:var(--muted); text-decoration:none; font-size:.84rem; }} .nav-links a:hover {{ color:var(--paper); }}
    .nav-cta,.cta {{ display:inline-flex; align-items:center; justify-content:center; text-decoration:none; border:1px solid var(--mint); color:var(--ink); background:var(--mint); padding:11px 17px; border-radius:999px; font-weight:750; font-size:.82rem; }} .nav-cta:hover,.cta:hover {{ background:#b9f5d5; }}
    .hero {{ position:relative; padding:94px 0 100px; }} .hero-grid {{ display:grid; grid-template-columns:1.02fr .98fr; gap:78px; align-items:center; }}
    .eyebrow {{ color:var(--copper); text-transform:uppercase; letter-spacing:.18em; font:700 .68rem ui-monospace,monospace; }} h1 {{ margin:20px 0 24px; max-width:720px; font:500 clamp(3.2rem,7vw,6.6rem)/.94 Georgia,serif; letter-spacing:-.055em; }} h1 em {{ color:var(--mint); font-style:italic; }} .lede {{ color:var(--muted); max-width:520px; font-size:1.12rem; line-height:1.7; }} .hero-actions {{ display:flex; gap:13px; flex-wrap:wrap; margin-top:32px; }} .ghost {{ color:var(--paper); border:1px solid #4a5951; background:transparent; }} .ghost:hover {{ border-color:var(--paper); background:rgba(255,255,255,.04); }}
    .signal {{ position:relative; min-height:390px; border:1px solid #394a41; background:linear-gradient(145deg,rgba(21,35,29,.9),rgba(10,15,13,.96)); padding:23px; box-shadow:0 35px 90px rgba(0,0,0,.35); overflow:hidden; }} .signal::before {{ content:""; position:absolute; width:360px; height:360px; border:1px solid rgba(142,231,189,.18); border-radius:50%; right:-150px; top:-130px; box-shadow:0 0 0 28px rgba(142,231,189,.03),0 0 0 58px rgba(142,231,189,.025); }} .signal::after {{ content:""; position:absolute; left:-20%; right:-20%; top:52%; height:1px; background:linear-gradient(90deg,transparent,var(--mint),transparent); opacity:.45; animation:scan 5s ease-in-out infinite; }} @keyframes scan {{ 0%,100% {{ transform:translateY(-90px); opacity:0; }} 50% {{ transform:translateY(90px); opacity:.65; }} }}
    .signal-top {{ display:flex; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:17px; color:var(--muted); font:700 .67rem ui-monospace,monospace; text-transform:uppercase; letter-spacing:.1em; }} .live {{ color:var(--mint); }} .live::before {{ content:""; display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--mint); box-shadow:0 0 14px var(--mint); margin-right:8px; }} .signal h2 {{ position:relative; margin:48px 0 8px; font:500 2.1rem/1.04 Georgia,serif; max-width:400px; }} .signal p {{ position:relative; color:var(--muted); margin:0; font-size:.92rem; }} .signal-rule {{ position:relative; display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:center; margin-top:48px; }} .signal-rule .line {{ height:1px; background:linear-gradient(90deg,var(--mint),#46564d); }} .signal-rule .line:last-child {{ background:linear-gradient(90deg,#46564d,var(--rose)); }} .signal-rule .point {{ width:10px; height:10px; border-radius:50%; background:var(--mint); box-shadow:0 0 0 5px rgba(142,231,189,.12); }} .signal-rule .point.bad {{ background:var(--rose); box-shadow:0 0 0 5px rgba(239,120,144,.12); }} .signal-labels {{ display:flex; justify-content:space-between; margin-top:12px; color:var(--muted); font: .7rem ui-monospace,monospace; }}
    .proof-strip {{ border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:21px 0; }} .proof-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:24px; }} .proof-item {{ color:var(--muted); font-size:.78rem; }} .proof-item strong {{ display:block; color:var(--paper); font:500 1.45rem Georgia,serif; margin-bottom:4px; }}
    section {{ position:relative; padding:88px 0; border-bottom:1px solid var(--line); }} .section-grid {{ display:grid; grid-template-columns:.8fr 1.2fr; gap:80px; }} h3 {{ margin:16px 0; font:500 clamp(2rem,4vw,3.5rem)/1 Georgia,serif; letter-spacing:-.035em; }} .copy {{ color:var(--muted); font-size:1.02rem; line-height:1.75; max-width:620px; }} .steps {{ display:grid; gap:0; border-top:1px solid var(--line); }} .step {{ display:grid; grid-template-columns:54px 1fr; gap:20px; padding:21px 0; border-bottom:1px solid var(--line); }} .step-no {{ color:var(--copper); font: .75rem ui-monospace,monospace; }} .step strong {{ display:block; font-size:1rem; margin-bottom:5px; }} .step span {{ color:var(--muted); font-size:.88rem; }}
    footer {{ padding:30px 0 52px; color:var(--muted); font-size:.78rem; }} footer a {{ color:var(--mint); text-decoration:none; }}
    @media(max-width:820px) {{ .hero {{ padding:62px 0 70px; }} .hero-grid,.section-grid {{ grid-template-columns:1fr; gap:46px; }} h1 {{ font-size:clamp(3rem,15vw,5rem); }} .proof-grid {{ grid-template-columns:repeat(2,1fr); }} .nav-links a:not(.nav-cta) {{ display:none; }} }} @media(max-width:480px) {{ .wrap {{ padding:0 19px; }} .signal {{ min-height:350px; }} .proof-grid {{ gap:16px; }} }}
  </style>
</head>
<body>
  <nav><div class="wrap nav-in"><a class="brand" href="/">stand<span>ing</span></a><div class="nav-links"><a href="#how">How it works</a><a href="#proof">Evidence</a><a href="/console" class="nav-cta">Open console ↗</a></div></div></nav>
  <main>
    <section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">Temporal engineering control</div><h1>Code remembers.<br><em>Reasoning should too.</em></h1><p class="lede">Standing keeps the assumptions behind technical decisions alive. When the world changes, it finds the code still depending on yesterday’s certainty.</p><div class="hero-actions"><a class="cta" href="/console">Enter the console ↗</a><a class="cta ghost" href="#how">See the mechanism ↓</a></div></div><div class="signal"><div class="signal-top"><span>Standing / live monitor</span><span class="live">memory online</span></div><h2>{escape(title_text)}</h2><p>{escape(decision_id)} · current decision state: {escape(state)}</p><div class="signal-rule"><span class="line"></span><span class="point"></span><span class="line"></span><span class="point bad"></span></div><div class="signal-labels"><span>THEN · {escape(required)}</span><span>NOW · {escape(current)} days</span></div></div></div></section>
    <div class="proof-strip"><div class="wrap proof-grid"><div class="proof-item"><strong>bitemporal</strong>valid time + knowledge time</div><div class="proof-item"><strong>exact paths</strong>intent connected to code</div><div class="proof-item"><strong>fail closed</strong>unknown never passes</div><div class="proof-item"><strong>onchain proof</strong>ACP · EAS · Sibyl</div></div></div>
    <section id="how"><div class="wrap section-grid"><div><div class="eyebrow">The idea</div><h3>A decision has standing only while its reasons remain true.</h3></div><div><p class="copy">Most systems can tell you what changed. Standing tells you what that change means for the decisions your team already made—and whether a new code change is still safe to merge.</p><div class="steps"><div class="step"><div class="step-no">01</div><div><strong>Remember the why</strong><span>Human-confirmed decisions, assumptions, and governed paths live in Sibyl Memory.</span></div></div><div class="step"><div class="step-no">02</div><div><strong>Verify the world</strong><span>Stale evidence triggers a verifier; typed observations are recorded through Base EAS.</span></div></div><div class="step"><div class="step-no">03</div><div><strong>Re-evaluate the code</strong><span>Standing resolves change versus conflict, then returns STANDS, EXPIRED, UNKNOWN, or CONTESTED.</span></div></div></div></div></div></section>
    <section id="proof"><div class="wrap section-grid"><div><div class="eyebrow">See it happen</div><h3>From drift to a safe replacement.</h3><p class="copy">Open the console to move through the complete lifecycle: inspect the original decision, travel through its evidence, break the assumption, see the exact path block, then record what replaced it.</p><a class="cta" href="/console">Open Standing console ↗</a></div><div class="signal" style="min-height:280px"><div class="signal-top"><span>Evidence chain</span><span class="live">verified path</span></div><div class="steps" style="margin-top:34px;border-top:0"><div class="step"><div class="step-no">A</div><div><strong>Decision → assumption</strong><span>{escape(decision_id)} · {escape(required)}</span></div></div><div class="step"><div class="step-no">B</div><div><strong>Observation → standing</strong><span>365 days → 90 days · evidence remains historical</span></div></div><div class="step"><div class="step-no">C</div><div><strong>Block → replacement</strong><span>Exact governed path · supersession · ALLOW</span></div></div></div></div></div></section>
  </main>
  <footer><div class="wrap">Standing · temporal system of record for engineering intent · <a href="https://github.com/Jennycruzy/standing" target="_blank" rel="noreferrer">source ↗</a> · <a href="/console">console ↗</a></div></footer>
</body></html>'''


def render_dashboard_html(payload: Mapping[str, Any], *, page_title: str = "Standing — engineering intent") -> str:
    """Render an interactive self-contained dashboard shell."""

    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    # JSON is placed inside a script element; escape HTML-significant chars so
    # persisted decision text cannot terminate the script tag.
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = escape(page_title, quote=True)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #101412; color: #f0ede5; --green:#b4d7bd; --green-strong:#8cc89e; --amber:#e4bd7b; --red:#e58f8b; --purple:#b6a7d6; --line:#2d3932; --panel:#171d1a; --panel-2:#1c241f; --muted:#98a69d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #101412; min-height: 100vh; }}
    body::before {{ content:''; position:fixed; inset:0; pointer-events:none; background:radial-gradient(ellipse at 88% -10%, rgba(111,151,119,.13), transparent 32%), radial-gradient(ellipse at 0% 100%, rgba(164,109,75,.07), transparent 29%); }}
    main {{ position:relative; max-width: 1540px; margin: 0 auto; padding: 30px 42px 80px; display:grid; grid-template-columns:224px minmax(0,1fr); gap:42px; }}
    .topbar {{ position:sticky; top:0; z-index:10; display:flex; align-items:center; gap:22px; padding:13px max(28px, calc((100vw - 1456px) / 2)); border-bottom:1px solid var(--line); background:rgba(16,20,18,.94); backdrop-filter:blur(18px); }}
    .brand {{ color:var(--green); font:600 1.02rem Georgia,serif; letter-spacing:.08em; }}
    .workspace-name {{ color:#d4d8d1; font-size:.82rem; padding-left:22px; border-left:1px solid var(--line); }}
    .system {{ display:flex; align-items:center; gap:8px; color:var(--muted); font-size:.68rem; letter-spacing:.06em; text-transform:uppercase; }}
    .pulse {{ width:7px; height:7px; border-radius:50%; background:var(--green-strong); box-shadow:0 0 0 4px rgba(140,200,158,.11); }}
    nav {{ margin-left:auto; display:flex; align-items:center; gap:8px; }}
    nav a {{ color:var(--muted); text-decoration:none; font-size:.69rem; letter-spacing:.04em; padding:7px 10px; border-radius:6px; }} nav a:hover, nav a.active {{ color:var(--ink, #101412); background:var(--green); }}
    .rail {{ position:sticky; top:76px; align-self:start; padding:10px 0 0; color:var(--muted); font-size:.76rem; }}
    .rail-title {{ color:#f0ede5; font:600 1.02rem Georgia,serif; letter-spacing:.08em; margin-bottom:34px; }} .rail-title span {{ color:var(--green-strong); }}
    .rail-group {{ margin:0 0 30px; }} .rail-group strong {{ display:block; color:#637168; font-size:.64rem; font-weight:700; margin:0 0 9px 13px; letter-spacing:.12em; text-transform:uppercase; }} .rail a {{ display:flex; align-items:center; gap:9px; color:#a1ada4; text-decoration:none; padding:9px 12px; border-left:2px solid transparent; border-radius:0 7px 7px 0; }} .rail a::before {{ content:' '; width:4px; height:4px; border:1px solid #66756c; border-radius:50%; }} .rail a:hover,.rail a.active {{ color:#f0ede5; border-left-color:var(--green-strong); background:rgba(140,200,158,.09); }} .rail a.active::before {{ background:var(--green-strong); border-color:var(--green-strong); }} .rail-note {{ border-top:1px solid var(--line); padding:16px 12px 0; line-height:1.55; color:#718078; }}
    .console-content {{ min-width:0; }}
    .hero {{ padding:18px 0 25px; border-bottom:1px solid var(--line); }}
    .hero-row {{ display:flex; align-items:end; justify-content:space-between; gap:30px; }} .hero-status {{ display:flex; gap:8px; align-items:center; color:#9aa89f; font: .68rem ui-monospace,monospace; text-transform:uppercase; letter-spacing:.08em; white-space:nowrap; }} .hero-status::before {{ content:""; width:7px; height:7px; border-radius:50%; background:var(--green-strong); box-shadow:0 0 0 4px rgba(140,200,158,.1); }}
    .thesis {{ max-width:760px; color:#a5b0a8; font-size:.96rem; line-height:1.65; margin-bottom:0; }}
    .eyebrow {{ color: var(--green); text-transform: uppercase; letter-spacing: .14em; font: 750 .68rem ui-monospace, SFMono-Regular, Menlo, monospace; }}
    h1, h2, h3 {{ margin: .35rem 0 .8rem; }}
    h1 {{ font:500 clamp(2.25rem, 5vw, 4.4rem)/.95 Georgia,serif; letter-spacing:-.04em; max-width:850px; }}
    h2 {{ font-size: 1.1rem; }}
    .muted {{ color: #98a69d; }}
    .disclosure {{ border: 1px solid #75613a; border-left:3px solid var(--amber); background: #211c13; color: #e7cf9e; padding: 13px 16px; border-radius: 8px; margin: 14px 0; line-height:1.55; }}
    .card {{ background: rgba(23,29,26,.88); border: 1px solid var(--line); border-radius: 10px; padding: 25px; margin-top: 16px; box-shadow: 0 16px 48px rgba(0,0,0,.14); }}
    .card > h2, .toolbar > h2 {{ font-family:Inter, ui-sans-serif, system-ui, sans-serif; letter-spacing:-.025em; font-weight:650; }}
    .finding {{ position:relative; border-color:#714048; background:rgba(39,27,29,.78); padding:30px; overflow:hidden; }}
    .finding::after {{ content:""; position:absolute; right:-70px; top:-120px; width:300px; height:300px; border:1px solid rgba(229,143,139,.13); border-radius:50%; pointer-events:none; }}
    .finding.stands {{ border-color:#3b6a4f; background:rgba(24,42,31,.82); }} .finding.stands::after {{ border-color:rgba(180,215,189,.15); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .metric {{ background: var(--panel); border: 1px solid #2a3730; border-radius: 8px; padding: 15px; }}
    .label {{ color: #819188; text-transform: uppercase; letter-spacing: .1em; font: 750 .63rem ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .value {{ margin-top: 5px; font-size: 1.15rem; font-weight: 800; overflow-wrap: anywhere; }}
    .expired, .blocked {{ color: var(--red); }} .stands, .allow {{ color: var(--green); }} .unknown {{ color: var(--amber); }} .contested {{ color: var(--purple); }}
    button {{ border: 1px solid #52665a; border-radius: 7px; background: #27352c; color: #f0ede5; padding: 10px 13px; cursor: pointer; font: 700 .74rem Inter, ui-sans-serif, system-ui, sans-serif; letter-spacing:.01em; margin: 4px 5px 0 0; }}
    button:hover {{ border-color:var(--green); background:#344a3a; }} button.danger {{ border-color:#95545c; background:#4a292f; }} button.safe {{ border-color:#557f62; background:#294533; }}
    .toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }} .toolbar h2::before {{ content:""; }}
    .graph {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
    .node {{ padding: 14px; background: #202b24; border: 1px solid #3f5647; border-radius: 8px; min-width: 130px; }}
    button.node {{ text-align: left; color: #e5edf8; font: inherit; }}
    button.node:focus-visible {{ outline: 2px solid #70e0bd; outline-offset: 2px; }}
    .arrow {{ color: var(--green); font-size: 1.1rem; }}
    .timeline {{ width: 100%; accent-color: var(--green); }}
    .timeline-row {{ display: flex; justify-content: space-between; color: #8fa19a; font-size: .8rem; }}
    details {{ border-top: 1px solid var(--line); padding: 13px 0; }} summary {{ cursor: pointer; font-weight: 650; }}
    pre, code {{ font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; color: #b4c8bf; font-size: .78rem; }}
    table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; padding: 9px; border-bottom: 1px solid var(--line); vertical-align: top; }} th {{ color: #8fa19a; font-size: .7rem; text-transform: uppercase; }}
    a {{ color:var(--green); }}
    blockquote {{ margin-left:0; border-left:2px solid #365248; padding-left:14px; color:#b7c8c0; }}
    .console-section {{ display:none; }} .console-section.active {{ display:block; animation: reveal .22s ease-out; }} @keyframes reveal {{ from {{ opacity:0; transform:translateY(4px); }} to {{ opacity:1; transform:none; }} }}
    .section-intro {{ display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:18px; }} .section-intro p {{ max-width:620px; margin:0; line-height:1.55; }}
    .overview-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:16px; }} .overview-grid .metric {{ min-height:92px; }}
    .activity-row {{ display:grid; grid-template-columns:150px 170px 1fr; gap:15px; padding:12px 0; border-bottom:1px solid var(--line); align-items:start; }} .activity-row:last-child {{ border-bottom:0; }} .activity-time {{ color:#7e8c84; font: .68rem ui-monospace,monospace; }} .activity-event {{ color:var(--green); text-transform:uppercase; font:700 .64rem ui-monospace,monospace; letter-spacing:.06em; }}
    .chain {{ display:grid; grid-template-columns:repeat(5,1fr); gap:0; margin-top:18px; }} .chain-step {{ position:relative; padding:14px 15px 14px 0; border-top:1px solid #405247; }} .chain-step:not(:last-child)::after {{ content:'→'; position:absolute; right:12px; top:10px; color:var(--green); }} .chain-step strong {{ display:block; font-size:.82rem; margin-top:5px; }} .chain-step span {{ color:var(--muted); font-size:.75rem; line-height:1.4; }}
    .provenance-row {{ display:grid; grid-template-columns:140px 1fr; gap:12px; padding:9px 0; border-bottom:1px solid var(--line); }} .provenance-row .label {{ padding-top:3px; }}
    .comparison-grid {{ display:grid; grid-template-columns:170px repeat(2,minmax(0,1fr)); gap:1px; background:var(--line); border:1px solid var(--line); border-radius:8px; overflow:hidden; }} .comparison-grid > * {{ margin:0; border:0; border-radius:0; }} .comparison-head {{ background:#263128; color:#c8d6cc; padding:12px 14px; font:700 .67rem ui-monospace,monospace; letter-spacing:.08em; }} .comparison-label {{ background:#131a16; color:#9aa79e; padding:15px 14px; font-size:.78rem; }} .comparison-grid .metric {{ min-height:0; padding:15px 14px; }}
    @media (max-width:1100px) {{ main {{ grid-template-columns:190px minmax(0,1fr); gap:28px; padding-left:26px; padding-right:26px; }} .chain {{ grid-template-columns:repeat(3,1fr); }} }}
    @media (max-width:900px) {{ main {{ grid-template-columns:1fr; gap:0; }} .rail {{ position:static; display:flex; align-items:center; gap:18px; padding:8px 0 16px; border-bottom:1px solid var(--line); }} .rail-group,.rail-note {{ display:none; }} .rail-title {{ margin:0; }} .rail::after {{ content:'Use the navigation above to move through the workspace'; color:#718078; font-size:.72rem; margin-left:auto; }} }}
    @media (max-width:680px) {{ main {{ padding:18px 14px 44px; }} .topbar {{ padding:10px 14px; }} nav {{ width:100%; margin-left:0; }} h1 {{ font-size:2.45rem; }} .hero-row {{ display:block; }} .hero-status {{ margin-top:18px; }} }}
    .off {{ opacity: .58; }}
    @media (max-width:620px) {{ .overview-grid {{ grid-template-columns:repeat(2,1fr); }} .chain {{ grid-template-columns:1fr; }} .chain-step:not(:last-child)::after {{ content:'↓'; right:auto; left:2px; top:auto; bottom:-13px; }} .activity-row {{ grid-template-columns:1fr; gap:4px; }} }}
  </style>
</head>
<body>
<header class="topbar"><a class="brand" href="/">STANDING</a><span class="workspace-name">Engineering intent workspace</span><div class="system"><span class="pulse"></span>Memory online</div><nav><a href="/" class="home-link">Product</a><a href="/console?view=evidence" data-view="evidence">Evidence</a><a href="/console?view=sandbox" data-view="sandbox">Sandbox</a></nav></header>
<main>
  <aside class="rail"><div class="rail-title">stand<span>ing</span></div><div class="rail-group"><strong>Workspace</strong><a class="active" href="/console?view=overview" data-view="overview">Overview</a><a href="/console?view=reviews" data-view="reviews">Reviews</a><a href="/console?view=decisions" data-view="decisions">Decisions</a></div><div class="rail-group"><strong>System record</strong><a href="/console?view=evidence" data-view="evidence">Evidence</a><a href="/console?view=timeline" data-view="timeline">Timeline</a><a href="/console?view=evaluation" data-view="evaluation">Evaluation</a><a href="/console?view=activity" data-view="activity">Activity</a></div><div class="rail-group"><strong>Controlled environment</strong><a href="/console?view=sandbox" data-view="sandbox">Sandbox</a></div><div class="rail-note">A temporal system of record for engineering intent.<br><br>Every decision has a reason. Every reason has a lifespan.</div></aside>
  <div class="console-content">
  <div class="hero"><div class="hero-row"><div><div class="eyebrow">Standing Console / overview</div><h1 id="summary">Loading remembered reasoning…</h1><p class="thesis">A software decision has standing only while the facts that justified it remain true.</p></div><div class="hero-status">Product workspace</div></div></div>
  <div id="disclosure"></div>
  <section id="finding" class="card finding console-section" data-view="overview"></section>
  <section id="overviewStats" class="card console-section" data-view="overview"><div class="section-intro"><div><div class="eyebrow">Attention</div><h2>What requires engineering attention</h2></div><p class="muted">Standing keeps current findings, review gates, and evidence freshness in one place.</p></div><div id="overviewStatsGrid" class="overview-grid"></div></section>
  <section id="graphSection" class="card console-section" data-view="decisions">
    <div class="toolbar"><h2 style="margin-right:auto">Decision graph</h2><span class="muted">Code → decision → assumption → evidence → standing</span></div>
    <div id="graph" class="graph"></div>
  </section>
  <section id="timeline" class="card console-section" data-view="timeline">
    <div class="toolbar"><h2 style="margin-right:auto">Bitemporal time travel</h2><span id="selectedDate" class="muted"></span></div>
    <input id="timeSlider" class="timeline" type="range" min="0" max="1" value="1" step="1">
    <div class="timeline-row"><span>Decision made</span><span>World changed</span><span>Today</span></div>
    <div id="timeTravel" class="grid" style="margin-top:12px"></div>
  </section>
  <section id="review" class="card console-section" data-view="reviews">
    <div class="section-intro"><div><div class="eyebrow">Standing Review</div><h2>Change review</h2></div><span id="reviewResult" class="muted"></span></div>
    <p class="muted">The backend reviewer checks the exact stored governed path. Search results are candidates; they never block on their own.</p>
    <div id="prReview"></div>
  </section>
  <section id="proposalsSection" class="card console-section" data-view="decisions">
    <div class="toolbar"><h2 style="margin-right:auto">Human confirmation</h2><span class="muted">Model proposals never govern code automatically</span></div>
    <div id="proposals"></div>
  </section>
  <section id="memory" class="card console-section" data-view="evidence">
    <div class="section-intro"><div><div class="eyebrow">Memory Proof</div><h2>Compare with memory removed</h2></div><button id="memoryCompare" class="safe">RUN MEMORY PROOF</button></div>
    <p class="muted">This is a backend ablation: the same changed path is reviewed once with Sibyl context and once with a fresh empty store.</p>
    <div id="memoryComparison"></div>
  </section>
  <section id="waiverSection" class="card console-section" data-view="activity">
    <div class="toolbar"><h2 style="margin-right:auto">Waiver status</h2><span class="muted">Human-issued, temporary, and automatically expiring</span></div>
    <div id="waivers"></div>
  </section>
  <section id="activity" class="card console-section" data-view="activity"><div class="section-intro"><div><div class="eyebrow">Journal</div><h2>Activity</h2></div><span class="muted">Recorded in Sibyl Memory</span></div><div id="activityLog"></div></section>
  <section id="sandbox" class="card console-section" data-view="sandbox">
    <div class="section-intro"><div><div class="eyebrow">Sandbox controls</div><h2>Controlled scenario</h2></div><span class="muted">Fixed workflow · no arbitrary signing</span></div>
    <div class="disclosure">{escape(CONTROLLED_DISCLOSURE)}</div>
    <div class="toolbar">
      <button id="break" class="danger">BREAK ASSUMPTION</button>
      <button id="restore" class="safe">RESET SANDBOX</button>
      <button id="resolve" class="safe">RECORD REPLACEMENT DECISION</button>
      <button id="reviewAgain">RUN REVIEW</button>
      <button id="waiver">VIEW WAIVER POLICY</button>
    </div>
    <div id="actionResult" class="muted" style="margin-top:10px"></div>
  </section>
  <section id="realWorldSection" class="card console-section" data-view="evaluation"><div class="section-intro"><div><div class="eyebrow">Public repository evaluation</div><h2>Public cases</h2></div><span class="muted">Real evidence kept separate from the sandbox</span></div><div id="realWorld"></div></section>
  <section id="proof" class="card console-section" data-view="evidence"><div class="section-intro"><div><div class="eyebrow">Live historical verification path</div><h2>Partner evidence</h2></div><span class="muted">Completed records</span></div><div id="partnerProof"></div></section>
  <section id="provenanceSection" class="card console-section" data-view="evidence"><div class="section-intro"><div><div class="eyebrow">Evidence identity</div><h2>Provenance</h2></div><span class="muted">Human-readable first · raw record on demand</span></div><div id="provenance"></div></section>
  </div>
</main>
<script>
const initial = {encoded};
let model = initial;
let selectedTime = null;
const pathViews = {{'/console/reviews':'reviews','/console/decisions':'decisions','/console/evidence':'evidence','/console/timeline':'timeline','/console/evaluation':'evaluation','/console/activity':'activity','/console/sandbox':'sandbox'}};
let activeView = new URLSearchParams(window.location.search).get('view') || pathViews[window.location.pathname] || 'overview';
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const formatDate = (seconds) => seconds ? new Date(Number(seconds) * 1000).toISOString().slice(0,10) : '—';
const primary = () => model.primary_finding;
function render() {{
  $('summary').textContent = model.summary || 'Standing';
  $('disclosure').innerHTML = model.disclosure ? `<div class="disclosure">${{esc(model.disclosure)}}</div>` : '';
  const finding = primary();
  if (!finding) {{ $('finding').innerHTML = '<h2>No remembered decisions</h2><p class="muted">Standing has no engineering intent to evaluate yet.</p>'; $('finding').className = 'card finding console-section stands'; }}
  else {{
    const ev = finding.evaluation || {{}}; const condition = (ev.conditions || [])[0] || {{}};
    $('finding').className = 'card finding console-section ' + String(ev.state || '').toLowerCase();
    $('finding').innerHTML = `<div class="eyebrow">Primary engineering finding</div><h2>${{esc(finding.body.title || finding.decision_id)}}</h2><div class="grid"><div class="metric"><div class="label">Decision</div><div class="value">${{esc(finding.decision_id)}}</div></div><div class="metric"><div class="label">Required</div><div class="value">${{esc(condition.predicate || '—')}}</div></div><div class="metric"><div class="label">Current</div><div class="value">${{esc(condition.accepted_value ?? 'unknown')}}</div></div><div class="metric"><div class="label">Affected</div><div class="value">${{(finding.body.governed_paths || []).length}} files</div></div><div class="metric"><div class="label">Status</div><div class="value ${{String(ev.state || '').toLowerCase()}}">${{esc(ev.state || 'UNKNOWN')}}</div></div></div><p class="muted">${{esc(finding.body.description || '')}}</p>`;
  }}
  renderOverview(); renderGraph(finding); renderTimeTravel(finding); renderPr(finding); renderProposals(); renderMemory(); renderWaivers(); renderActivity(); renderRealWorld(); renderPartnerProof(); renderProvenance(finding); setView(activeView);
}}
function setView(view) {{
  const known = ['overview','reviews','decisions','evidence','timeline','evaluation','activity','sandbox'];
  activeView = known.includes(view) ? view : 'overview';
  document.querySelectorAll('.console-section').forEach((section) => section.classList.toggle('active', section.dataset.view === activeView));
  document.querySelectorAll('[data-view]').forEach((item) => item.classList.toggle('active', item.dataset.view === activeView));
  if (window.location.pathname.startsWith('/console')) history.replaceState(null, '', `/console?view=${{activeView}}`);
}}
function renderOverview() {{
  const decisions = model.decisions || []; const findings = decisions.filter((d) => d.active && d.evaluation?.state !== 'STANDS'); const waivers = model.waivers || []; const real = model.real_world || {{}};
  $('overviewStatsGrid').innerHTML = `<div class="metric"><div class="label">Needs attention</div><div class="value ${{findings.length ? 'expired' : 'stands'}}">${{findings.length}}</div><p class="muted">Current decisions outside STANDS</p></div><div class="metric"><div class="label">Reviewed paths</div><div class="value">${{esc(model.review_result?.decisions_found ?? 0)}}</div><p class="muted">Exact governed-path matches</p></div><div class="metric"><div class="label">Evidence due</div><div class="value">${{decisions.reduce((n,d) => n + (d.evaluation?.state === 'UNKNOWN' ? 1 : 0), 0)}}</div><p class="muted">Unknown or stale conditions</p></div><div class="metric"><div class="label">Public cases</div><div class="value">${{esc(real.reviewed_case_count ?? 0)}}</div><p class="muted">Hand-reviewed source chains</p></div>`;
}}
function renderGraph(finding) {{
  if (!finding) {{ $('graph').innerHTML = '<span class="muted">No graph available.</span>'; return; }}
  const condition = (finding.conditions || [])[0] || {{}}; const observations = condition.observations || []; const state = (finding.evaluation || {{}}).state || 'UNKNOWN';
  const node = (target, label, value, className = '') => `<button type="button" class="node ${{className}}" data-graph-target="${{esc(target)}}"><div class="label">${{esc(label)}}</div><b>${{esc(value)}}</b></button>`;
  $('graph').innerHTML = [node('code', 'Code', (finding.body.governed_paths || [])[0] || '—'),`<span class="arrow">↓</span>`,node('decision', 'Decision', finding.decision_id),`<span class="arrow">↓</span>`,node('assumption', 'Assumption', condition.rule?.predicate || '—'),`<span class="arrow">↓</span>`,node('evidence', 'Accepted evidence', `${{observations.length}} observation(s)`),`<span class="arrow">↓</span>`,node('standing', 'Standing', state, String(state).toLowerCase())].join('');
  document.querySelectorAll('[data-graph-target]').forEach((element) => element.addEventListener('click', () => {{
    const target = element.dataset.graphTarget;
    const view = target === 'code' ? 'reviews' : target === 'evidence' ? 'evidence' : target === 'decision' || target === 'assumption' || target === 'standing' ? 'decisions' : 'overview';
    setView(view);
    $('actionResult').textContent = `Selected ${{target}} in the decision graph.`;
  }}));
}}
function allObservations(finding) {{ return ((finding?.conditions || [])[0]?.observations || []).filter((x) => x && x.effective_from != null); }}
function renderTimeTravel(finding) {{
  const timeline = Array.isArray(model.sandbox?.time_travel) ? model.sandbox.time_travel : []; const slider = $('timeSlider'); const last = Math.max(0, timeline.length - 1); slider.max = String(last); slider.value = String(selectedTime == null ? last : Math.min(selectedTime, last)); const row = timeline[Number(slider.value)] || {{}}; const point = Number(row.point || Math.floor(Date.now()/1000)); selectedTime = Number(slider.value); const valid = row.valid || null; const known = row.known || null; $('selectedDate').textContent = `Selected: ${{formatDate(point)}}`;
  $('timeTravel').innerHTML = `<div class="metric"><div class="label">What we now believe was true</div><div class="value">${{esc(valid?.value ?? 'unknown')}} ${{esc(valid?.unit || '')}}</div><p class="muted">Valid time: ${{formatDate(valid?.effective_from)}}</p></div><div class="metric"><div class="label">What Standing knew then</div><div class="value">${{esc(known?.value ?? 'not recorded')}} ${{esc(known?.unit || '')}}</div><p class="muted">Knowledge cutoff: ${{formatDate(point)}}</p></div><div class="metric"><div class="label">Assessment</div><div class="value">${{esc(row.assessment || 'No temporal answer')}}</div><p class="muted">Standing never rewrites the original record.</p></div>`;
}}
function renderPr() {{ const result = model.review_result || {{}}; const decisions = result.decisions || []; const row = decisions[0] || {{}}; const evaluation = row.evaluation || {{}}; const state = row.state || result.state || 'UNKNOWN'; const action = row.action || result.action || 'ALLOW'; $('reviewResult').textContent = result.decisions_found ? `${{result.decisions_found}} exact governed decision(s) found` : 'No exact governed decision found'; $('prReview').innerHTML = `<div class="grid"><div class="metric"><div class="label">Changed path</div><div class="value"><code>${{esc((result.changed_paths || ['src/archive.py'])[0])}}</code></div><p class="muted">Resolved by the backend reviewer</p></div><div class="metric"><div class="label">Governing decision</div><div class="value">${{esc(row.decision_id || 'None')}}</div><p class="muted">${{esc(evaluation.conditions?.[0]?.predicate || 'No remembered assumption')}}</p></div><div class="metric"><div class="label">Standing</div><div class="value ${{String(state).toLowerCase()}}">${{esc(state)}}</div><p class="muted">${{esc(evaluation.conditions?.[0]?.message || 'No decision governs this path.')}}</p></div><div class="metric"><div class="label">Review action</div><div class="value ${{action === 'BLOCK' ? 'blocked' : 'allow'}}">${{esc(action)}}</div><p class="muted">Exact-path validation is authoritative.</p></div></div>`; }}
function renderProposals() {{ const proposals = model.proposals || []; if (!proposals.length) {{ $('proposals').innerHTML = '<p class="muted">No decision proposals are waiting for review.</p>'; return; }} $('proposals').innerHTML = proposals.map((p) => `<details><summary>${{esc(p.proposal_id)}} — ${{esc(p.status)}}</summary><p><b>${{esc(p.title || p.decision_id)}}</b></p><p class="muted">Derived from ${{esc(p.artifact_path || 'engineering artifact')}} · ${{esc(p.artifact_type || '')}}</p><blockquote>${{esc(p.source_sentence || 'No source sentence recorded.')}}</blockquote><p class="muted">${{esc(p.rationale || '')}}</p>${{p.status === 'PENDING' ? '<button data-proposal-action="confirm-proposal" class="safe">CONFIRM PROPOSAL</button><button data-proposal-action="reject-proposal" class="danger">REJECT PROPOSAL</button>' : `<span class="value">${{esc(p.status)}}${{p.confirmed_by ? ' by ' + esc(p.confirmed_by) : ''}}</span>`}}</details>`).join(''); document.querySelectorAll('[data-proposal-action]').forEach((button) => button.addEventListener('click', () => action(button.dataset.proposalAction))); }}
function renderMemory() {{ const comparison = model.memory_comparison; if (!comparison) {{ $('memoryComparison').innerHTML = '<div class="metric"><div class="label">Ready to run</div><div class="value">Backend ablation pending</div><p class="muted">Run the memory proof to compare the same review with and without remembered intent.</p></div>'; return; }} const on = comparison.memory_on || {{}}; const off = comparison.memory_removed || {{}}; $('memoryComparison').innerHTML = `<div class="comparison-grid"><div class="comparison-head"></div><div class="comparison-head">MEMORY PRESENT</div><div class="comparison-head">MEMORY REMOVED</div><div class="comparison-label">External fact</div><div class="metric">${{esc(on.current_fact)}} days</div><div class="metric">${{esc(off.current_fact)}} days</div><div class="comparison-label">Decision found</div><div class="metric">${{esc(on.decision_found || 'None')}}</div><div class="metric">${{esc(off.decision_found || 'None')}}</div><div class="comparison-label">Original assumption</div><div class="metric">${{esc(on.assumption || 'Missing')}}</div><div class="metric">${{esc(off.assumption || 'Missing')}}</div><div class="comparison-label">Expiry identified</div><div class="metric ${{on.expiry_detected ? 'blocked' : 'stands'}}">${{on.expiry_detected ? 'Yes' : 'No'}}</div><div class="metric">No</div><div class="comparison-label">Protection</div><div class="metric ${{on.protection === 'BLOCK' ? 'blocked' : 'allow'}}">${{esc(on.protection)}}</div><div class="metric unknown">${{esc(off.protection)}}</div></div><p class="muted" style="margin-top:16px">${{esc(comparison.conclusion || '')}}</p>`; }}
function renderWaivers() {{ const waivers = model.waivers || []; if (!waivers.length) {{ $('waivers').innerHTML = '<p class="muted">No human waiver is recorded. A non-standing result remains blocked.</p>'; return; }} $('waivers').innerHTML = waivers.map((w) => `<div class="metric"><div class="label">${{esc(w.status || 'WAIVER')}}</div><div class="value">${{esc(w.waiver_id || '—')}} · ${{esc(w.decision_id || '—')}}</div><p class="muted">Approved by ${{esc(w.issued_by || '—')}} · expires ${{esc(formatDate(w.expires_at))}} · ${{esc(w.reason || '')}}</p></div>`).join(''); }}
function renderRealWorld() {{ const proof = model.real_world || {{}}; const cases = proof.cases || []; const evaluation = model.evaluation || {{}}; const statusClass = proof.status === 'REVIEWED' ? 'stands' : 'unknown'; $('realWorld').innerHTML = `<div class="grid"><div class="metric"><div class="label">Review status</div><div class="value ${{statusClass}}">${{esc(proof.status || 'PENDING')}}</div></div><div class="metric"><div class="label">Public cases</div><div class="value">${{esc(proof.reviewed_case_count ?? 0)}}</div></div><div class="metric"><div class="label">Controlled scenarios</div><div class="value">${{esc(evaluation.controlled_scenarios ?? 0)}}</div></div></div><div class="disclosure">Real-world evidence is reported separately from the controlled scenario. No benchmark score is claimed until all prediction artifacts are recorded.</div>${{cases.length ? cases.map((c) => `<details><summary>${{esc(c.case_id)}} · ${{esc(c.review_status || 'PENDING HUMAN REVIEW')}}</summary><p class="muted">${{esc(c.repository || '')}}</p><p><a href="${{esc(c.decision_url)}}" target="_blank" rel="noreferrer">Decision artifact ↗</a> · <a href="${{esc(c.historical_ground_truth_url)}}" target="_blank" rel="noreferrer">Historical source ↗</a> · <a href="${{esc(c.current_ground_truth_url)}}" target="_blank" rel="noreferrer">Current source ↗</a></p><p class="muted">${{esc(c.disclosure || '')}}</p></details>`).join('') : '<p class="muted">No source-linked public case is recorded.</p>'}}`; }}
function renderPartnerProof() {{ const proof = model.partner_proof || {{}}; const agents = proof.agents || []; $('partnerProof').innerHTML = `<p>${{esc(proof.summary || 'No completed verification record is available.')}}</p><div class="chain"><div class="chain-step"><div class="label">01 · Virtuals ACP</div><strong>Job ${{esc(proof.acp_job_id || '—')}} · completed</strong><span><a href="${{esc(proof.acp_public_url || '#')}}" target="_blank" rel="noreferrer">Open platform ↗</a><br><a href="${{esc(proof.acp_job_url || '#')}}" target="_blank" rel="noreferrer">Technical record ↗</a><br>API access may require credentials.</span></div><div class="chain-step"><div class="label">02 · Verifier</div><strong>Source extracted</strong><span>Typed value returned with extraction provenance.</span></div><div class="chain-step"><div class="label">03 · Base EAS</div><strong>Observation recorded</strong><span><a href="${{esc(proof.eas_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open Base transaction ↗</a></span></div><div class="chain-step"><div class="label">04 · Sibyl</div><strong>Read back and stored</strong><span>Condition reference and standing journal updated.</span></div><div class="chain-step"><div class="label">05 · ERC-8004</div><strong>Outcome recorded</strong><span><a href="${{esc(proof.erc8004_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open feedback ↗</a></span></div></div><div class="metric" style="margin-top:18px"><div class="label">Registered agent identities</div><div class="value">${{agents.length}} Virtuals profiles</div><p>${{agents.map((agent) => `<span style="display:block;margin-top:8px"><b>${{esc(agent.name)}}</b> · ${{esc(agent.role)}} · profile <code>${{esc(agent.virtual_agent_id)}}</code></span>`).join('')}}</p><p><a href="${{esc(proof.acp_directory_url || '#')}}" target="_blank" rel="noreferrer">Open agent directory ↗</a> · <a href="${{esc(proof.acp_scan_url || '#')}}" target="_blank" rel="noreferrer">Open ACP scan ↗</a></p><p class="muted">Registry profile IDs are displayed as identities; no ACP Entity ID is inferred from them.</p></div><details><summary>Evidence identity</summary><pre>${{esc(JSON.stringify({{eas_uid: proof.eas_uid, acp_job_id: proof.acp_job_id, erc8004_agent_id: proof.erc8004_agent_id}}, null, 2))}}</pre></details>`; }}
function renderProvenance(finding) {{ const rows = allObservations(finding); $('provenance').innerHTML = rows.length ? rows.map((x) => `<details><summary>${{esc(x.observation_uid)}} · ${{esc(x.value)}} ${{esc(x.unit || '')}}</summary><div class="provenance-row"><div class="label">Value</div><div>${{esc(x.value)}} ${{esc(x.unit || '')}}</div></div><div class="provenance-row"><div class="label">Effective</div><div>${{formatDate(x.effective_from)}}</div></div><div class="provenance-row"><div class="label">Observed / recorded</div><div>${{formatDate(x.observed_at)}} / ${{formatDate(x.recorded_at)}}</div></div><div class="provenance-row"><div class="label">Source</div><div><a href="${{esc(x.source_url || '#')}}" target="_blank" rel="noreferrer">${{esc(x.source_url || 'not recorded')}} ↗</a></div></div><div class="provenance-row"><div class="label">Extraction</div><div><code>${{esc(x.extraction_method || '—')}} · ${{esc(x.extraction_version || '—')}}</code></div></div><div class="provenance-row"><div class="label">Evidence hash</div><div><code>${{esc(x.evidence_hash || '—')}}</code></div></div><p class="muted">${{esc(x.notes || '')}}</p><details><summary>View raw record</summary><pre>${{esc(JSON.stringify(x, null, 2))}}</pre></details></details>`).join('') : '<p class="muted">No temporal observations are recorded.</p>'; }}
function renderActivity() {{ const rows = model.activity || []; $('activityLog').innerHTML = rows.length ? rows.map((row) => `<div class="activity-row"><div class="activity-time">${{esc(row.timestamp || 'journal time')}}</div><div class="activity-event">${{esc(row.event || 'journal event')}}</div><div><b>${{esc(row.decision_id || 'Standing')}}</b><div class="muted">${{esc(row.detail || '')}}</div></div></div>`).join('') : '<p class="muted">No activity has been recorded yet.</p>'; }}
async function action(name) {{ try {{ const response = await fetch('/api/sandbox/' + name, {{method:'POST'}}); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'action failed'); if (name === 'waiver') {{ $('actionResult').textContent = body.disclosure + ' ' + body.status; setView('sandbox'); return; }} model = body; selectedTime = null; const messages = {{'break':'Controlled source changed: 365 → 90 days; the backend re-evaluated ACME-001.','reset':'Sandbox reset: ACME-001 is standing again.','resolve':'ACME-001 superseded by STORAGE-002.','confirm-proposal':'Human confirmation recorded; the proposal is now a decision.','reject-proposal':'Human rejection recorded; no decision was created.','review':'Backend review completed.','memory-comparison':'Memory proof completed against a fresh store.'}}; $('actionResult').textContent = messages[name] || 'Action completed.'; if (name === 'memory-comparison') setView('evidence'); else if (name === 'review') setView('reviews'); render(); }} catch (error) {{ $('actionResult').textContent = String(error); }} }}
document.querySelectorAll('[data-view]').forEach((item) => item.addEventListener('click', (event) => {{ if (item.tagName.toLowerCase() !== 'a' || item.getAttribute('href')?.startsWith('/console')) event.preventDefault(); setView(item.dataset.view); }})); $('timeSlider').addEventListener('input', () => {{ selectedTime = Number($('timeSlider').value); render(); }}); $('memoryCompare').addEventListener('click', () => action('memory-comparison')); $('break').addEventListener('click', () => action('break')); $('restore').addEventListener('click', () => action('reset')); $('resolve').addEventListener('click', () => action('resolve')); $('reviewAgain').addEventListener('click', () => action('review')); $('waiver').addEventListener('click', () => action('waiver')); render();
</script>
</body>
</html>'''


def serve_dashboard(app: DashboardApp, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Serve the Standing product surface and controlled-scenario endpoints."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    _respond_html(self, render_landing_html(app.state()))
                elif parsed.path == "/console":
                    _respond_html(self, render_dashboard_html(app.state()))
                elif parsed.path in {
                    "/console/reviews",
                    "/console/decisions",
                    "/console/evidence",
                    "/console/timeline",
                    "/console/evaluation",
                    "/console/activity",
                    "/console/sandbox",
                }:
                    _respond_html(self, render_dashboard_html(app.state()))
                elif parsed.path == "/api/state":
                    _respond_json(self, app.state())
                elif parsed.path == "/api/sandbox-source":
                    _respond_json(self, app.source())
                elif parsed.path == "/api/decisions":
                    _respond_json(self, {"decisions": app.state()["decisions"]})
                elif parsed.path.startswith("/api/decisions/"):
                    decision_id = unquote(parsed.path[len("/api/decisions/"):]).strip("/")
                    decision = next(
                        (item for item in app.state()["decisions"] if item.get("decision_id") == decision_id),
                        None,
                    )
                    if decision is None:
                        _respond_json(self, {"error": "decision not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        _respond_json(self, decision)
                elif parsed.path == "/api/reviews":
                    _respond_json(self, app.review())
                elif parsed.path.startswith("/api/evidence/"):
                    condition_key = unquote(parsed.path[len("/api/evidence/"):]).strip("/")
                    history = app.tools.condition_history(condition_key)
                    current = app.tools.current_condition(condition_key)
                    _respond_json(
                        self,
                        {
                            "condition_key": condition_key,
                            "current": None if current is None else current.as_dict(),
                            "history": [item.as_dict() for item in history],
                        },
                    )
                elif parsed.path == "/api/evaluation":
                    state = app.state()
                    _respond_json(self, state["evaluation"])
                elif parsed.path == "/api/partner-proof":
                    _respond_json(self, dict(PARTNER_PROOF))
                else:
                    _respond_json(self, {"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except (OSError, ValueError, ReviewerToolError, TemporalObservationError) as error:
                _respond_json(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                prefix = "/api/sandbox/"
                if not parsed.path.startswith(prefix):
                    _respond_json(self, {"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                action = parsed.path[len(prefix):]
                _respond_json(self, app.action(action))
            except (OSError, ValueError, ReviewerToolError, TemporalObservationError) as error:
                _respond_json(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return
    finally:
        server.server_close()


def _sandbox_observation(
    uid: str,
    value: int,
    effective_from: int,
    recorded_date: str,
    *,
    ref_uid: str | None = None,
) -> dict[str, Any]:
    recorded_at = parse_timestamp(recorded_date, label="recorded_at")
    body: dict[str, Any] = {
        "condition_key": SANDBOX_CONDITION,
        "value": value,
        "value_type": "number",
        "unit": "days",
        "effective_from": effective_from,
        "observed_at": recorded_at,
        "recorded_at": recorded_at,
        "source_url": SANDBOX_SOURCE_URL,
        "source_domain": "raw.githubusercontent.com",
        "source_type": "vendor_primary",
        "attester": "standing-attester",
        "operator_id": "standing-operator",
        "extraction_method": "JSON_PATH",
        "extraction_version": "retention-json-v1",
        "observation_uid": uid,
        "ref_uid": ref_uid,
        "evidence_hash": observation_evidence_hash(
            {"condition_key": SANDBOX_CONDITION, "value": value, "effective_from": effective_from}
        ),
        "notes": CONTROLLED_DISCLOSURE,
        "accepted": True,
        "controlled_scenario": True,
    }
    return body


def _entity_body(entity: Mapping[str, Any]) -> dict[str, Any]:
    body = entity.get("body")
    if not isinstance(body, dict):
        raise ReviewerToolError("Sibyl returned a record without a mapping body")
    return dict(body)


def _respond_json(handler: BaseHTTPRequestHandler, body: Mapping[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
    encoded = json.dumps(dict(body), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(encoded)))
    handler.send_header("cache-control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def _respond_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    encoded = html.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("content-type", "text/html; charset=utf-8")
    handler.send_header("content-length", str(len(encoded)))
    handler.send_header("cache-control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)
