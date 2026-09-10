"""Standing Console and controlled-scenario application."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time, time_ns
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

from .memory import MemoryStore, create_memory_store
from .model_review import DecisionProposal
from .reviewer import ReviewerToolError, ReviewerTools
from .temporal import TemporalObservationError, observation_evidence_hash, parse_timestamp


CONTROLLED_DISCLOSURE = (
    "CONTROLLED SCENARIO: FICTIONAL ACME. "
    "This sandbox uses fictional Acme data operated by Standing so the lifecycle "
    "can be reproduced safely. The control below replays the source change locally. "
    "Completed Virtuals ACP → source extraction → Base EAS records are shown separately "
    "as live historical proof."
)
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#242a26"/>
<circle cx="32" cy="32" r="20" fill="none" stroke="#8fbe9a" stroke-width="3"/>
<circle cx="32" cy="32" r="7" fill="#d39a6e"/>
</svg>"""
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
    "acp_job_url": "https://app.virtuals.io/acp/scan",
    "acp_api_url": "https://api.acp.virtuals.io/jobs/8453/77748",
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
                description="A non-blocking proposal retained to showcase the confirmation workflow.",
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
            f"sandbox-reset-{time_ns()}",
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
            f"{reviewed} human-reviewed public cases are recorded separately from the controlled scenario."
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


def render_landing_html(payload: Mapping[str, Any], *, page_title: str = "Standing | Engineering intent") -> str:
    """Render the public product introduction for the deployed service."""

    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = escape(page_title, quote=True)
    finding = payload.get("primary_finding")
    state = "UNKNOWN"
    decision_id = "Not recorded"
    title_text = "The reasoning behind every change."
    current = "Unknown"
    required = "Not recorded"
    state_note = "standing now"
    if isinstance(finding, Mapping):
        decision_id = str(finding.get("decision_id", "Not recorded"))
        body = finding.get("body")
        evaluation = finding.get("evaluation")
        if isinstance(body, Mapping):
            title_text = str(body.get("title", title_text))
        if isinstance(evaluation, Mapping):
            state = str(evaluation.get("state", state))
            state_note = "standing now" if state == "STANDS" else f"{state.lower()} · path at risk"
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
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <title>{title}</title>
  <style>
    :root {{ color-scheme:light; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f3f0e8; color:#202521; --bg:#f3f0e8; --paper:#202521; --muted:#656b65; --faint:#8a9089; --line:#d7d3c9; --line-strong:#aaa99f; --sage:#315f43; --sage-strong:#47795a; --copper:#9b5d32; --red:#a7443d; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; min-height:100vh; color:var(--paper); background:var(--bg); overflow-x:hidden; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.28; background-image:linear-gradient(rgba(42,50,44,.045) 1px,transparent 1px); background-size:100% 48px; }}
    body::after {{ content:""; position:fixed; inset:0; pointer-events:none; background:linear-gradient(115deg,rgba(255,255,255,.68),transparent 44%); }}
    .wrap {{ position:relative; max-width:1240px; margin:auto; padding:0 30px; }}
    nav {{ position:relative; z-index:2; border-bottom:1px solid var(--line); }} .nav-in {{ min-height:70px; display:flex; align-items:center; gap:18px; }}
    .brand {{ display:inline-flex; align-items:center; gap:10px; color:var(--paper); font-size:.78rem; font-weight:750; letter-spacing:.16em; text-decoration:none; }} .brand-mark {{ position:relative; width:21px; height:21px; display:grid; place-items:center; border:1px solid var(--sage-strong); border-radius:50%; }} .brand-mark::before {{ content:""; width:6px; height:6px; border-radius:50%; background:var(--sage); box-shadow:0 0 14px rgba(185,213,187,.42); }}
    .nav-links {{ margin-left:auto; display:flex; gap:7px; align-items:center; }} .nav-links a {{ color:var(--muted); padding:8px 10px; border:1px solid transparent; border-radius:3px; text-decoration:none; font-size:.7rem; letter-spacing:.04em; }} .nav-links a:hover {{ color:var(--paper); border-color:var(--line-strong); background:rgba(185,213,187,.06); }}
    .nav-cta,.cta {{ display:inline-flex; align-items:center; justify-content:center; text-decoration:none; border:1px solid #27352c; color:#fff; background:#27352c; padding:11px 16px; border-radius:5px; font-weight:750; font-size:.7rem; letter-spacing:.04em; text-transform:uppercase; }} .nav-cta:hover,.cta:hover {{ color:#fff; background:#365040; }}
    .hero {{ position:relative; padding:88px 0 92px; }} .hero-grid {{ display:grid; grid-template-columns:1fr .92fr; gap:76px; align-items:center; }}
    .eyebrow {{ color:var(--copper); text-transform:uppercase; letter-spacing:.16em; font:700 .61rem ui-monospace,monospace; }} h1 {{ margin:19px 0 23px; max-width:680px; color:var(--paper); font:500 clamp(3rem,6vw,5.6rem)/.94 Georgia,serif; letter-spacing:-.055em; }} h1 em {{ color:var(--sage); font-style:italic; }} .lede {{ color:var(--muted); max-width:520px; font-size:1.04rem; line-height:1.72; }} .hero-actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:30px; }} .ghost {{ color:var(--paper); border:1px solid var(--line-strong); background:transparent; }} .ghost:hover {{ color:var(--paper); border-color:var(--paper); background:rgba(255,255,255,.035); }}
    .signal {{ position:relative; min-height:390px; padding:26px; border:1px solid #343b36; border-left:3px solid #6ca27b; border-radius:6px; background:#202622; color:#edf0eb; box-shadow:0 28px 64px rgba(40,45,40,.16); }} .signal::before {{ content:""; position:absolute; top:0; right:0; width:42%; height:1px; background:#a76b43; opacity:.75; }}
    .signal-top {{ display:flex; justify-content:space-between; gap:14px; padding-bottom:16px; border-bottom:1px solid #3c443e; color:#aab3ac; font:700 .61rem ui-monospace,monospace; letter-spacing:.09em; text-transform:uppercase; }} .live {{ color:#a8d0b1; white-space:nowrap; }} .live::before {{ content:""; display:inline-block; width:6px; height:6px; margin-right:8px; border-radius:50%; background:#78a986; }}
    .signal-decision {{ padding:34px 0 26px; }} .signal-id {{ color:#d39a6e; font:700 .67rem ui-monospace,monospace; letter-spacing:.1em; }} .signal h2 {{ margin:10px 0 8px; color:#f3f3ef; font:500 1.88rem/1.08 Georgia,serif; letter-spacing:-.025em; }} .signal p {{ margin:0; color:#aeb7b0; font-size:.82rem; line-height:1.55; }}
    .signal-ledger {{ border-top:1px solid #3c443e; }} .signal-row {{ display:grid; grid-template-columns:72px 1fr auto; align-items:center; gap:12px; padding:14px 0; border-bottom:1px solid #3c443e; }} .signal-row > span:first-child {{ color:#87928a; font:700 .59rem ui-monospace,monospace; letter-spacing:.12em; }} .signal-row strong {{ color:#a9d0b2; font:650 1.12rem ui-monospace,monospace; }} .signal-row > span:last-child {{ color:#9ea9a1; font-size:.68rem; text-align:right; }} .signal-row.bad strong {{ color:#efa098; }} .signal-row.bad > span:last-child {{ color:#c39490; }}
    .signal-foot {{ display:flex; justify-content:space-between; gap:12px; padding-top:18px; color:#87928a; font: .63rem ui-monospace,monospace; }} .signal-foot code {{ color:#c9d1ca; }}
    .proof-strip {{ border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:19px 0; }} .proof-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:24px; }} .proof-item {{ color:var(--muted); font-size:.73rem; line-height:1.45; }} .proof-item strong {{ display:block; margin-bottom:5px; color:var(--paper); font:650 1.16rem Georgia,serif; }}
    section {{ position:relative; padding:86px 0; border-bottom:1px solid var(--line); }} .section-grid {{ display:grid; grid-template-columns:.8fr 1.2fr; gap:80px; }} h3 {{ margin:16px 0; color:var(--paper); font:500 clamp(2rem,4vw,3.4rem)/1 Georgia,serif; letter-spacing:-.04em; }} .copy {{ color:var(--muted); font-size:.98rem; line-height:1.75; max-width:620px; }} .steps {{ display:grid; gap:0; border-top:1px solid var(--line); }} .step {{ display:grid; grid-template-columns:54px 1fr; gap:20px; padding:20px 0; border-bottom:1px solid var(--line); }} .step-no {{ color:var(--copper); font: .68rem ui-monospace,monospace; }} .step strong {{ display:block; margin-bottom:5px; color:var(--paper); font-size:.93rem; }} .step span {{ color:var(--muted); font-size:.82rem; line-height:1.55; }}
    footer {{ padding:28px 0 48px; color:var(--muted); font-size:.72rem; }} footer a {{ color:var(--sage); text-decoration:none; }}
    @media(max-width:820px) {{ .hero {{ padding:62px 0 70px; }} .hero-grid,.section-grid {{ grid-template-columns:1fr; gap:46px; }} h1 {{ font-size:clamp(3rem,15vw,5rem); }} .proof-grid {{ grid-template-columns:repeat(2,1fr); }} .nav-links a:not(.nav-cta) {{ display:none; }} }} @media(max-width:480px) {{ .wrap {{ padding:0 19px; }} .signal {{ min-height:350px; padding:19px; }} .proof-grid {{ gap:16px; }} .signal-row {{ grid-template-columns:58px 1fr; }} .signal-row > span:last-child {{ grid-column:2; text-align:left; }} }}
  </style>
</head>
<body>
  <nav><div class="wrap nav-in"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span>STANDING</span></a><div class="nav-links"><a href="#how">How it works</a><a href="#proof">Evidence</a><a href="/console" class="nav-cta">Open console ↗</a></div></div></nav>
  <main>
    <section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">Temporal engineering control</div><h1>Code remembers.<br><em>Reasoning should too.</em></h1><p class="lede">Standing keeps the assumptions behind technical decisions alive. When the world changes, it finds the code still depending on yesterday’s certainty.</p><div class="hero-actions"><a class="cta" href="/console">Enter the console ↗</a><a class="cta ghost" href="#how">See the mechanism ↓</a></div></div><div class="signal"><div class="signal-top"><span>Decision / archive retention</span><span class="live">controlled scenario</span></div><div class="signal-decision"><div class="signal-id">{escape(decision_id)}</div><h2>{escape(title_text)}</h2><p>One assumption connects a vendor fact to the code that depends on it.</p></div><div class="signal-ledger"><div class="signal-row"><span>THEN</span><strong>365 days</strong><span>decision recorded</span></div><div class="signal-row bad"><span>NOW</span><strong>{escape(current)} days</strong><span>{escape(state_note)}</span></div></div><div class="signal-foot"><span>governed path</span><code>src/archive.py</code></div></div></div></section>
    <div class="proof-strip"><div class="wrap proof-grid"><div class="proof-item"><strong>bitemporal</strong>valid time + knowledge time</div><div class="proof-item"><strong>exact paths</strong>intent connected to code</div><div class="proof-item"><strong>fail closed</strong>unknown never passes</div><div class="proof-item"><strong>onchain proof</strong>ACP · EAS · Sibyl</div></div></div>
    <section id="how"><div class="wrap section-grid"><div><div class="eyebrow">The idea</div><h3>A decision has standing only while its reasons remain true.</h3></div><div><p class="copy">Most systems can tell you what changed. Standing tells you what that change means for decisions your team already made and whether a new code change is still safe to merge.</p><div class="steps"><div class="step"><div class="step-no">01</div><div><strong>Remember the why</strong><span>Human-confirmed decisions, assumptions, and governed paths live in Sibyl Memory.</span></div></div><div class="step"><div class="step-no">02</div><div><strong>Verify the world</strong><span>Stale evidence triggers a verifier; typed observations are recorded through Base EAS.</span></div></div><div class="step"><div class="step-no">03</div><div><strong>Re-evaluate the code</strong><span>Standing resolves change versus conflict, then returns STANDS, EXPIRED, UNKNOWN, or CONTESTED.</span></div></div></div></div></div></section>
    <section id="proof"><div class="wrap section-grid"><div><div class="eyebrow">See it happen</div><h3>From drift to a safe replacement.</h3><p class="copy">Open the console to move through the complete lifecycle: inspect the original decision, travel through its evidence, break the assumption, see the exact path block, then record what replaced it.</p><a class="cta" href="/console">Open Standing console ↗</a></div><div class="signal" style="min-height:280px"><div class="signal-top"><span>Evidence chain</span><span class="live">verified path</span></div><div class="steps" style="margin-top:34px;border-top:0"><div class="step"><div class="step-no">A</div><div><strong>Decision → assumption</strong><span>{escape(decision_id)} · {escape(required)}</span></div></div><div class="step"><div class="step-no">B</div><div><strong>Observation → standing</strong><span>365 days → 90 days · evidence remains historical</span></div></div><div class="step"><div class="step-no">C</div><div><strong>Block → replacement</strong><span>Exact governed path · supersession · ALLOW</span></div></div></div></div></div></section>
  </main>
  <footer><div class="wrap">Standing · temporal system of record for engineering intent · <a href="https://github.com/Jennycruzy/standing" target="_blank" rel="noreferrer">source ↗</a> · <a href="/console">console ↗</a></div></footer>
</body></html>'''


def render_dashboard_html(payload: Mapping[str, Any], *, page_title: str = "Standing | Engineering intent") -> str:
    """Render an interactive self-contained dashboard shell."""

    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    # JSON is placed inside a script element; escape HTML-significant chars so
    # persisted decision text cannot terminate the script tag.
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = escape(page_title, quote=True)
    mode_label = "SANDBOX" if payload.get("controlled_scenario") else "LIVE WORKSPACE"
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Avenir Next", Avenir, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eeece5;
      color: #252a26;
      --bg: #eeece5;
      --surface: #fbfaf7;
      --surface-raised: #ffffff;
      --surface-soft: #f4f2ec;
      --ink: #252a26;
      --muted: #687069;
      --faint: #8a918a;
      --line: #d8d5cc;
      --line-strong: #aaa99f;
      --sage: #326548;
      --sage-strong: #477b59;
      --copper: #9e6137;
      --amber: #a97925;
      --red: #a94842;
      --purple: #755d8e;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--ink); }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.3; background-image:linear-gradient(rgba(37,42,38,.04) 1px,transparent 1px); background-size:100% 52px; }}
    body::after {{ display:none; }}
    a {{ color:var(--sage); text-decoration:none; }}
    a:hover {{ color:#1e4931; }}
    code, pre, .activity-time {{ font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .topbar {{ position:sticky; top:0; z-index:10; min-height:66px; display:flex; align-items:center; gap:18px; padding:0 max(28px, calc((100vw - 1480px) / 2)); border-bottom:1px solid #343b36; background:rgba(32,38,34,.97); color:#eef0ec; backdrop-filter:blur(14px); }}
    .brand {{ display:inline-flex; align-items:center; gap:10px; color:#f3f4f1; font-size:.78rem; font-weight:800; letter-spacing:.13em; }}
    .brand-mark {{ position:relative; width:22px; height:22px; display:grid; place-items:center; border:1px solid var(--sage-strong); border-radius:50%; }}
    .brand-mark::before {{ content:""; width:6px; height:6px; background:var(--sage); border-radius:50%; box-shadow:0 0 16px rgba(185,213,187,.48); }}
    .workspace-name {{ padding-left:18px; border-left:1px solid #49514b; color:#b6bdb7; font-size:.73rem; letter-spacing:.03em; }}
    .topbar-context {{ color:var(--copper); font-size:.64rem; letter-spacing:.08em; }}
    .topbar-right {{ margin-left:auto; display:flex; align-items:center; gap:20px; }}
    .system {{ display:flex; align-items:center; gap:8px; color:#bdc5be; font-size:.62rem; letter-spacing:.08em; }}
    .pulse {{ width:6px; height:6px; border-radius:50%; background:var(--sage-strong); box-shadow:0 0 0 4px rgba(143,199,154,.10); }}
    .release-mark {{ color:var(--faint); font-size:.59rem; letter-spacing:.06em; }}
    nav {{ display:flex; align-items:center; gap:4px; }}
    nav a {{ color:#b9c0ba; padding:8px 10px; border:1px solid transparent; border-radius:4px; font-size:.67rem; letter-spacing:.03em; }}
    nav a:hover, nav a.active {{ color:#fff; border-color:#59635b; background:#303934; }}
    main {{ position:relative; max-width:1540px; margin:0 auto; padding:36px 42px 96px; display:grid; grid-template-columns:226px minmax(0,1fr); gap:48px; }}
    .rail {{ position:sticky; top:94px; align-self:start; min-height:calc(100vh - 130px); padding:24px 18px 20px; border:1px solid #343b36; border-radius:6px; background:#242a26; color:#aeb6af; font-size:.78rem; box-shadow:0 18px 46px rgba(41,45,41,.10); display:flex; flex-direction:column; }}
    .rail-context {{ padding:2px 12px 20px; border-bottom:1px solid #414943; margin-bottom:20px; }}
    .rail-kicker {{ color:#ce9369; font-size:.64rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }}
    .rail-name {{ margin-top:10px; color:#f0f2ef; font-size:1.25rem; font-weight:650; line-height:1.08; letter-spacing:-.02em; }}
    .rail-state {{ display:flex; align-items:center; gap:8px; margin-top:13px; color:#99a39b; font-size:.63rem; font-weight:650; letter-spacing:.06em; text-transform:uppercase; }}
    .rail-state::before {{ content:""; width:6px; height:6px; background:var(--sage-strong); border-radius:50%; }}
    .rail-group {{ margin:0 0 20px; }}
    .rail-group strong {{ display:block; margin:0 0 8px 12px; color:#858f87; font-size:.62rem; font-weight:700; letter-spacing:.11em; text-transform:uppercase; }}
    .rail a {{ display:flex; align-items:center; gap:11px; color:#adb6ae; padding:9px 12px; border-left:2px solid transparent; border-radius:0 4px 4px 0; }}
    .rail a::before {{ content:attr(data-icon); width:17px; color:#667268; font: .58rem ui-monospace,monospace; letter-spacing:0; }}
    .rail a:hover, .rail a.active {{ color:#fff; border-left-color:#81ad8d; background:#303934; }}
    .rail a.active::before {{ color:var(--sage-strong); }}
    .rail-footer {{ position:static; margin-top:auto; padding:16px 12px 0; border-top:1px solid #404841; color:#929b94; font-size:.68rem; line-height:1.55; }}
    .rail-footer-label {{ display:block; margin-bottom:6px; color:#a5aea7; font-size:.61rem; font-weight:700; letter-spacing:.10em; text-transform:uppercase; }}
    .console-content {{ min-width:0; }}
    .hero {{ padding:4px 0 30px; border-bottom:1px solid var(--line); }}
    .breadcrumb {{ display:flex; align-items:center; gap:9px; color:var(--faint); font-size:.67rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase; }}
    .breadcrumb .eyebrow {{ color:var(--sage-strong); }}
    .breadcrumb .slash {{ color:var(--line-strong); }}
    .hero-row {{ display:flex; align-items:end; justify-content:space-between; gap:36px; margin-top:24px; }}
    .hero-status {{ display:flex; gap:8px; align-items:center; color:#b1bbb2; font: .63rem ui-monospace,monospace; letter-spacing:.10em; text-transform:uppercase; white-space:nowrap; }}
    .hero-status::before {{ content:""; width:6px; height:6px; border-radius:50%; background:var(--sage-strong); }}
    .hero-aside {{ min-width:166px; padding-left:22px; border-left:1px solid var(--line); }}
    .hero-aside .label {{ color:var(--faint); }}
    .hero-aside strong {{ display:block; margin-top:9px; color:var(--sage); font-size:.86rem; letter-spacing:.05em; }}
    .hero-aside span:last-child {{ display:block; margin-top:6px; color:var(--faint); font-size:.68rem; }}
    .thesis {{ max-width:720px; margin:14px 0 0; color:#687069; font-size:.91rem; line-height:1.65; }}
    .eyebrow {{ color:var(--sage-strong); text-transform:uppercase; letter-spacing:.09em; font-size:.67rem; font-weight:750; }}
    h1, h2, h3 {{ margin:.35rem 0 .8rem; }}
    h1 {{ max-width:850px; color:var(--ink); font-size:clamp(2.25rem,4vw,3.75rem); font-weight:650; line-height:1; letter-spacing:-.045em; }}
    h2 {{ color:#2b302c; font-size:1.05rem; letter-spacing:-.015em; }}
    .muted {{ color:var(--muted); }}
    .disclosure {{ margin:15px 0 0; padding:13px 16px; border:1px solid #d7c59c; border-left:3px solid var(--amber); border-radius:4px; background:#fbf4e3; color:#765d2b; font-size:.77rem; line-height:1.55; }}
    .card {{ margin-top:18px; padding:26px; border:1px solid var(--line); border-radius:6px; background:rgba(255,255,255,.88); box-shadow:0 12px 34px rgba(46,49,45,.055); }}
    .card > h2, .toolbar > h2 {{ font-family:Inter,ui-sans-serif,system-ui,sans-serif; font-weight:650; }}
    .finding {{ position:relative; overflow:hidden; padding:30px; border-color:#dbc1bd; border-left:3px solid var(--red); background:linear-gradient(108deg,#fff7f5,#fff 72%); }}
    .finding.stands {{ border-color:#bfd1c4; border-left-color:var(--sage-strong); background:linear-gradient(108deg,#f2f8f3,#fff 72%); }}
    .finding-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:28px; }}
    .finding-id {{ margin-top:10px; color:var(--copper); font:700 .72rem ui-monospace,monospace; letter-spacing:.10em; }}
    .finding-title {{ max-width:650px; margin:8px 0 0; color:#272c28; font-size:1.52rem; line-height:1.16; letter-spacing:-.025em; }}
    .finding-description {{ max-width:650px; margin:10px 0 0; color:#687069; font-size:.84rem; line-height:1.55; }}
    .finding-posture {{ min-width:148px; padding-left:22px; border-left:1px solid rgba(236,149,139,.28); text-align:right; }}
    .finding.stands .finding-posture {{ border-left-color:rgba(143,199,154,.28); }}
    .finding-posture .label {{ color:#7b837c; }}
    .status-mark {{ margin-top:8px; color:var(--red); font:700 1.25rem ui-monospace,monospace; letter-spacing:.06em; }}
    .status-mark.stands {{ color:var(--sage); }}
    .status-mark.unknown {{ color:var(--amber); }}
    .status-mark.contested {{ color:var(--purple); }}
    .finding-posture p {{ margin:7px 0 0; color:#737b74; font-size:.68rem; line-height:1.45; }}
    .finding-rule {{ display:flex; align-items:center; gap:11px; margin:27px 0 23px; color:#737c74; font: .65rem ui-monospace,monospace; }}
    .finding-rule .rule-line {{ height:1px; flex:1; background:linear-gradient(90deg,var(--sage-strong),#536458); }}
    .finding-rule .rule-line:last-of-type {{ background:linear-gradient(90deg,#536458,var(--red)); }}
    .finding-rule .rule-point {{ width:7px; height:7px; border:1px solid var(--sage-strong); background:#fff; border-radius:50%; }}
    .finding-rule .rule-point.bad {{ border-color:var(--red); background:var(--red); box-shadow:0 0 0 4px rgba(233,149,139,.10); }}
    .finding-rule strong {{ color:var(--ink); font-weight:650; }}
    .finding-ledger {{ display:grid; grid-template-columns:1.35fr 1fr 1fr 1.2fr; border-top:1px solid #dfdcd4; }}
    .ledger-cell {{ min-height:86px; padding:16px 18px 4px 0; border-bottom:1px solid #dfdcd4; }}
    .ledger-cell + .ledger-cell {{ padding-left:18px; border-left:1px solid #dfdcd4; }}
    .ledger-value {{ display:block; margin-top:9px; color:#303631; font-size:.86rem; line-height:1.42; overflow-wrap:anywhere; }}
    .ledger-value.bad {{ color:var(--red); }}
    .ledger-value.good {{ color:var(--sage); }}
    .ledger-note {{ display:block; margin-top:6px; color:#808780; font-size:.67rem; line-height:1.4; }}
    .finding-footer {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding-top:17px; color:#737b74; font-size:.72rem; }}
    .finding-footer .footer-state {{ color:var(--red); font:700 .63rem ui-monospace,monospace; letter-spacing:.08em; }}
    .finding.stands .finding-footer .footer-state {{ color:var(--sage); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; }}
    .metric {{ min-width:0; padding:15px; border:1px solid #d9d7cf; border-radius:4px; background:var(--surface-soft); }}
    .label {{ color:#737d75; text-transform:uppercase; letter-spacing:.07em; font-size:.64rem; font-weight:750; }}
    .value {{ margin-top:7px; color:#2f3530; font-size:1.03rem; font-weight:700; overflow-wrap:anywhere; }}
    .expired, .blocked {{ color:var(--red); }} .stands, .allow {{ color:var(--sage); }} .unknown {{ color:var(--amber); }} .contested {{ color:var(--purple); }}
    button {{ margin:4px 7px 0 0; padding:10px 13px; border:1px solid #9ba49c; border-radius:4px; background:#f8f8f5; color:#303630; cursor:pointer; font:700 .68rem Inter,ui-sans-serif,system-ui,sans-serif; letter-spacing:.05em; text-transform:uppercase; }}
    button:hover {{ border-color:var(--sage); background:#eef4ef; }} button.danger {{ border-color:#c99590; background:#fff2f0; color:#923e38; }} button.safe {{ border-color:#8eaf97; background:#edf6ef; color:#2f6441; }}
    button:focus-visible, a:focus-visible {{ outline:2px solid var(--sage); outline-offset:3px; }}
    .toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; }} .toolbar h2 {{ margin-right:auto; }}
    .graph {{ display:flex; flex-wrap:wrap; align-items:stretch; gap:0; padding-top:14px; }}
    .node {{ position:relative; min-width:142px; max-width:220px; padding:14px 15px; border:1px solid #ccd2cc; border-radius:4px; background:#f7f8f4; text-align:left; }}
    .node::after {{ content:""; position:absolute; left:0; right:0; bottom:-1px; height:2px; background:var(--sage-strong); opacity:.38; }}
    button.node {{ color:#303630; font:inherit; }} button.node:hover {{ border-color:var(--sage-strong); background:#edf4ee; }}
    .node-index {{ display:block; margin-bottom:10px; color:var(--copper); font:700 .59rem ui-monospace,monospace; }}
    .node b {{ display:block; margin-top:6px; color:#303630; font-size:.78rem; line-height:1.35; overflow-wrap:anywhere; }}
    button.node.expired::after, button.node.blocked::after {{ background:var(--red); }}
    .arrow {{ display:grid; place-items:center; min-width:32px; color:#718476; font-size:.82rem; }}
    .timeline {{ width:100%; margin:20px 0 8px; accent-color:var(--sage-strong); }}
    .timeline-row {{ display:flex; justify-content:space-between; color:#747d76; font-size:.63rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
    .time-travel-grid {{ margin-top:18px; }}
    .time-travel-card {{ min-height:170px; padding:20px; border:1px solid var(--line); border-radius:3px; background:#faf9f5; }}
    .time-travel-card .value {{ font-size:1.38rem; }}
    .time-travel-card.world {{ border-top:2px solid var(--copper); }} .time-travel-card.known {{ border-top:2px solid var(--sage-strong); }} .time-travel-card.assessment {{ border-top:2px solid #788678; }}
    details {{ padding:14px 0; border-top:1px solid var(--line); }} details:last-child {{ border-bottom:1px solid var(--line); }} summary {{ color:#303630; cursor:pointer; font-size:.82rem; font-weight:650; }}
    pre {{ margin:12px 0 0; padding:14px; border-radius:4px; background:#252b27; white-space:pre-wrap; overflow-wrap:anywhere; color:#cbd5cd; font: .72rem/1.6 ui-monospace,monospace; }}
    table {{ width:100%; border-collapse:collapse; }} th, td {{ padding:12px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:#737d75; font-size:.64rem; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }}
    blockquote {{ margin:13px 0; padding-left:14px; border-left:2px solid #73917b; color:#555e57; line-height:1.55; }}
    .console-section {{ display:none; }} .console-section.active {{ display:block; animation:reveal .18s ease-out; }} @keyframes reveal {{ from {{ opacity:0; transform:translateY(3px); }} to {{ opacity:1; transform:none; }} }}
    .section-intro {{ display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:18px; }} .section-intro p {{ max-width:620px; margin:0; line-height:1.55; }}
    .overview-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:0; margin-top:15px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
    .overview-grid .metric {{ min-height:92px; padding:16px 18px 14px 0; border:0; border-radius:0; background:transparent; }} .overview-grid .metric + .metric {{ padding-left:18px; border-left:1px solid var(--line); }}
    .activity-row {{ display:grid; grid-template-columns:132px 190px 1fr; gap:15px; padding:13px 0; border-bottom:1px solid var(--line); align-items:start; }} .activity-row:last-child {{ border-bottom:0; }} .activity-time {{ color:#7e8a81; font-size:.63rem; }} .activity-event {{ color:var(--sage); font-size:.64rem; font-weight:750; letter-spacing:.06em; text-transform:uppercase; }}
    .chain {{ display:grid; grid-template-columns:repeat(5,1fr); gap:0; margin-top:20px; }} .chain-step {{ position:relative; min-height:134px; padding:15px 19px 12px 0; border-top:1px solid #9aafa0; }} .chain-step + .chain-step {{ padding-left:19px; border-left:1px solid var(--line); }} .chain-step:not(:last-child)::after {{ content:'→'; position:absolute; right:-7px; top:10px; z-index:1; color:var(--sage-strong); background:var(--surface); padding:0 3px; }} .chain-step strong {{ display:block; margin-top:8px; color:#303630; font-size:.78rem; line-height:1.35; }} .chain-step span {{ display:block; margin-top:8px; color:var(--muted); font-size:.69rem; line-height:1.5; }}
    .provenance-row {{ display:grid; grid-template-columns:145px 1fr; gap:12px; padding:10px 0; border-bottom:1px solid var(--line); }} .provenance-row .label {{ padding-top:3px; }}
    .comparison-grid {{ display:grid; grid-template-columns:170px repeat(2,minmax(0,1fr)); gap:1px; background:var(--line); border:1px solid var(--line); border-radius:4px; overflow:hidden; }} .comparison-grid > * {{ margin:0; border:0; border-radius:0; }} .comparison-head {{ background:#29312c; color:#dce5de; padding:12px 14px; font:700 .61rem ui-monospace,monospace; letter-spacing:.09em; }} .comparison-label {{ background:#eceae3; color:#69716a; padding:15px 14px; font-size:.74rem; }} .comparison-grid .metric {{ min-height:0; padding:15px 14px; }}
    .off {{ opacity:.58; }}
    @media (max-width:1120px) {{ main {{ grid-template-columns:200px minmax(0,1fr); gap:30px; padding-left:28px; padding-right:28px; }} .chain {{ grid-template-columns:repeat(3,1fr); }} .finding-ledger {{ grid-template-columns:repeat(2,1fr); }} .ledger-cell + .ledger-cell {{ padding-left:0; border-left:0; }} .ledger-cell:nth-child(even) {{ padding-left:18px; border-left:1px solid rgba(255,255,255,.09); }} }}
    @media (max-width:900px) {{ main {{ grid-template-columns:1fr; gap:20px; }} .rail {{ position:static; min-height:0; display:flex; align-items:center; gap:18px; padding:16px 18px; }} .rail-context {{ min-width:175px; margin:0; padding:0 18px 0 0; border:0; }} .rail-name {{ margin-top:7px; font-size:1.18rem; }} .rail-state {{ margin-top:9px; }} .rail-group,.rail-footer {{ display:none; }} .rail::after {{ content:'Use the navigation above to move through the workspace'; margin-left:auto; color:#9ba49d; font-size:.68rem; }} .finding-head {{ display:block; }} .finding-posture {{ margin-top:20px; padding:14px 0 0; border-left:0; border-top:1px solid rgba(169,72,66,.22); text-align:left; }} .finding.stands .finding-posture {{ border-top-color:rgba(71,123,89,.24); }} }}
    @media (max-width:680px) {{ main {{ padding:22px 14px 55px; }} .topbar {{ flex-wrap:wrap; gap:10px; padding:12px 14px; }} .workspace-name,.release-mark {{ display:none; }} .topbar-right {{ width:100%; margin-left:0; justify-content:space-between; }} nav {{ margin-left:auto; }} nav a {{ padding:7px 8px; }} .hero {{ padding-top:5px; }} .hero-row {{ display:block; }} .hero-aside {{ margin-top:22px; padding:14px 0 0; border-left:0; border-top:1px solid var(--line); }} h1 {{ font-size:2.7rem; }} .card {{ padding:20px 17px; }} .finding {{ padding:22px 18px; }} .finding-ledger {{ grid-template-columns:1fr; }} .ledger-cell,.ledger-cell:nth-child(even) {{ padding-left:0; border-left:0; }} .graph {{ display:grid; grid-template-columns:1fr; gap:0; }} .node {{ max-width:none; }} .arrow {{ min-height:26px; transform:rotate(90deg); }} .chain {{ grid-template-columns:1fr; }} .chain-step,.chain-step + .chain-step {{ min-height:0; padding:14px 0; border-left:0; }} .chain-step:not(:last-child)::after {{ content:'↓'; right:auto; left:1px; top:auto; bottom:-8px; }} .activity-row {{ grid-template-columns:1fr; gap:4px; }} .comparison-grid {{ grid-template-columns:1fr; }} .comparison-head:not(:first-child) {{ display:none; }} .comparison-label {{ border-top:1px solid var(--line) !important; }} .comparison-grid .metric {{ border-bottom:1px solid var(--line); }} .overview-grid {{ grid-template-columns:repeat(2,1fr); }} .overview-grid .metric:nth-child(odd) {{ padding-left:0; }} .overview-grid .metric:nth-child(even) {{ padding-left:14px; }} .overview-grid .metric:nth-child(n+3) {{ border-top:1px solid var(--line); }} }}
  </style>
</head>
<body>
<header class="topbar"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span>STANDING</span></a><span class="workspace-name">Engineering intent workspace <span class="topbar-context">/ {escape(mode_label)}</span></span><div class="topbar-right"><div class="system"><span class="pulse"></span><span>Sibyl connected</span></div><span class="release-mark">EVIDENCE LEDGER</span><nav><a href="/" class="home-link">Product</a><a href="/console?view=evidence" data-view="evidence">Evidence</a><a href="/console?view=sandbox" data-view="sandbox">Sandbox</a></nav></div></header>
<main>
  <aside class="rail"><div class="rail-context"><div class="rail-kicker">Workspace</div><div class="rail-name">Engineering<br>intent</div><div class="rail-state">Memory online</div></div><div class="rail-group"><strong>Workspace</strong><a class="active" data-icon="01" href="/console?view=overview" data-view="overview">Overview</a><a data-icon="02" href="/console?view=reviews" data-view="reviews">Reviews</a><a data-icon="03" href="/console?view=decisions" data-view="decisions">Decisions</a></div><div class="rail-group"><strong>System record</strong><a data-icon="04" href="/console?view=evidence" data-view="evidence">Evidence</a><a data-icon="05" href="/console?view=timeline" data-view="timeline">Timeline</a><a data-icon="06" href="/console?view=evaluation" data-view="evaluation">Evaluation</a><a data-icon="07" href="/console?view=activity" data-view="activity">Activity</a></div><div class="rail-group"><strong>Controlled environment</strong><a data-icon="08" href="/console?view=sandbox" data-view="sandbox">Sandbox</a></div><div class="rail-footer"><span class="rail-footer-label">Sibyl journal</span>Decision context, evidence, and review state stay linked.</div></aside>
  <div class="console-content">
  <div class="hero"><div class="breadcrumb"><span class="eyebrow">Standing Console</span><span class="slash">/</span><span>Overview</span></div><div class="hero-row"><div><h1 id="summary">Loading remembered reasoning…</h1><p class="thesis">A software decision has standing only while the facts that justified it remain true.</p></div><div class="hero-aside"><div class="label">System posture</div><strong id="postureMark">RECONSTRUCTING</strong><span>Decision state from the backend ledger</span></div></div></div>
  <div id="disclosure" class="console-section" data-view="sandbox"></div>
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
const pathView = window.location.pathname.startsWith('/console/decisions/') ? 'decisions' : window.location.pathname.startsWith('/console/evidence/') ? 'evidence' : pathViews[window.location.pathname];
let activeView = new URLSearchParams(window.location.search).get('view') || pathView || 'overview';
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const formatDate = (seconds) => seconds ? new Date(Number(seconds) * 1000).toISOString().slice(0,10) : 'Not recorded';
const primary = () => model.primary_finding;
function render() {{
  $('summary').textContent = model.summary || 'Standing';
  $('disclosure').innerHTML = model.disclosure ? `<div class="disclosure">${{esc(model.disclosure)}}</div>` : '';
  const finding = primary();
  const currentState = String(finding?.evaluation?.state || 'UNKNOWN');
  $('postureMark').textContent = currentState === 'STANDS' ? 'STANDING' : currentState;
  $('postureMark').className = `hero-posture-value ${{currentState.toLowerCase()}}`;
  if (!finding) {{ $('finding').innerHTML = '<h2>No remembered decisions</h2><p class="muted">Standing has no engineering intent to evaluate yet.</p>'; $('finding').className = 'card finding console-section stands'; }}
  else {{
    const ev = finding.evaluation || {{}}; const condition = (ev.conditions || [])[0] || {{}}; const reference = (finding.conditions || [])[0]?.reference || {{}};
    const status = String(ev.state || 'UNKNOWN'); const current = reference.accepted_value ?? condition.accepted_value ?? 'unknown'; const unit = reference.unit || condition.unit || 'days';
    const paths = Array.isArray(finding.body?.governed_paths) ? finding.body.governed_paths : []; const action = ev.action || (status === 'STANDS' ? 'ALLOW' : 'BLOCK');
    $('finding').className = 'card finding console-section ' + String(ev.state || '').toLowerCase();
    $('finding').innerHTML = `<div class="finding-head"><div><div class="eyebrow">Current decision</div><div class="finding-id">${{esc(finding.decision_id)}}</div><h2 class="finding-title">${{esc(finding.body.title || finding.decision_id)}}</h2><p class="finding-description">${{esc(finding.body.description || '')}}</p></div><div class="finding-posture"><div class="label">Posture</div><div class="status-mark ${{status.toLowerCase()}}">${{esc(status)}}</div><p>${{esc(action)}} · ${{paths.length}} governed path(s)</p></div></div><div class="finding-rule"><span class="rule-line"></span><span class="rule-point"></span><strong>${{esc(condition.predicate || 'Required condition')}}</strong><span class="rule-point bad"></span><span class="rule-line"></span></div><div class="finding-ledger"><div class="ledger-cell"><div class="label">Reason</div><span class="ledger-value">${{esc(finding.body.description || 'Decision rationale recorded in Sibyl.')}}</span></div><div class="ledger-cell"><div class="label">Required</div><span class="ledger-value"><code>${{esc(condition.predicate || 'Not recorded')}}</code></span><span class="ledger-note">Human-confirmed condition</span></div><div class="ledger-cell"><div class="label">Current evidence</div><span class="ledger-value ${{status === 'STANDS' ? 'good' : 'bad'}}">${{esc(current)}} ${{esc(unit)}}</span><span class="ledger-note">Effective ${{formatDate(reference.effective_from || condition.effective_from)}}</span></div><div class="ledger-cell"><div class="label">Governed code</div><span class="ledger-value"><code>${{esc(paths.join(' · ') || 'No path recorded')}}</code></span><span class="ledger-note">Exact-path validation</span></div></div><div class="finding-footer"><span class="footer-state">${{esc(status)}} / ${{esc(action)}}</span><a href="/console?view=reviews">Open affected review ↗</a></div>`;
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
  $('overviewStatsGrid').innerHTML = `<div class="metric"><div class="label">Needs attention</div><div class="value ${{findings.length ? 'expired' : 'stands'}}">${{findings.length}}</div><p class="muted">Decisions outside STANDS</p></div><div class="metric"><div class="label">Paths checked</div><div class="value">${{esc(model.review_result?.decisions_found ?? 0)}}</div><p class="muted">Exact governed-path matches</p></div><div class="metric"><div class="label">Evidence due</div><div class="value">${{decisions.reduce((n,d) => n + (d.evaluation?.state === 'UNKNOWN' ? 1 : 0), 0)}}</div><p class="muted">Unknown or stale conditions</p></div><div class="metric"><div class="label">Public cases</div><div class="value">${{esc(real.reviewed_case_count ?? 0)}}</div><p class="muted">Hand-reviewed source chains</p></div>`;
}}
function renderGraph(finding) {{
  if (!finding) {{ $('graph').innerHTML = '<span class="muted">No graph available.</span>'; return; }}
  const condition = (finding.conditions || [])[0] || {{}}; const observations = condition.observations || []; const state = (finding.evaluation || {{}}).state || 'UNKNOWN';
  const node = (target, index, label, value, className = '') => `<button type="button" class="node ${{className}}" data-graph-target="${{esc(target)}}"><span class="node-index">${{esc(index)}}</span><div class="label">${{esc(label)}}</div><b>${{esc(value)}}</b></button>`;
  $('graph').innerHTML = [node('code', '01', 'Code', (finding.body.governed_paths || [])[0] || 'Not recorded'),`<span class="arrow">→</span>`,node('decision', '02', 'Decision', finding.decision_id),`<span class="arrow">→</span>`,node('assumption', '03', 'Assumption', condition.rule?.predicate || 'Not recorded'),`<span class="arrow">→</span>`,node('evidence', '04', 'Accepted evidence', `${{observations.length}} observation(s)`),`<span class="arrow">→</span>`,node('standing', '05', 'Standing', state, String(state).toLowerCase())].join('');
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
  $('timeTravel').innerHTML = `<div class="time-travel-card world"><div class="label">What we now believe was true</div><div class="value">${{esc(valid?.value ?? 'unknown')}} ${{esc(valid?.unit || '')}}</div><p class="muted">Valid time: ${{formatDate(valid?.effective_from)}}</p></div><div class="time-travel-card known"><div class="label">What Standing knew then</div><div class="value">${{esc(known?.value ?? 'not recorded')}} ${{esc(known?.unit || '')}}</div><p class="muted">Knowledge cutoff: ${{formatDate(point)}}</p></div><div class="time-travel-card assessment"><div class="label">Assessment</div><div class="value">${{esc(row.assessment || 'No temporal answer')}}</div><p class="muted">Standing never rewrites the original record.</p></div>`;
}}
function renderPr() {{ const result = model.review_result || {{}}; const decisions = result.decisions || []; const row = decisions[0] || {{}}; const evaluation = row.evaluation || {{}}; const state = row.state || result.state || 'UNKNOWN'; const action = row.action || result.action || 'ALLOW'; $('reviewResult').textContent = result.decisions_found ? `${{result.decisions_found}} exact governed decision(s) found` : 'No exact governed decision found'; $('prReview').innerHTML = `<div class="grid"><div class="metric"><div class="label">Changed path</div><div class="value"><code>${{esc((result.changed_paths || ['src/archive.py'])[0])}}</code></div><p class="muted">Resolved by the backend reviewer</p></div><div class="metric"><div class="label">Governing decision</div><div class="value">${{esc(row.decision_id || 'None')}}</div><p class="muted">${{esc(evaluation.conditions?.[0]?.predicate || 'No remembered assumption')}}</p></div><div class="metric"><div class="label">Standing</div><div class="value ${{String(state).toLowerCase()}}">${{esc(state)}}</div><p class="muted">${{esc(evaluation.conditions?.[0]?.message || 'No decision governs this path.')}}</p></div><div class="metric"><div class="label">Review action</div><div class="value ${{action === 'BLOCK' ? 'blocked' : 'allow'}}">${{esc(action)}}</div><p class="muted">Exact-path validation is authoritative.</p></div></div>`; }}
function renderProposals() {{ const proposals = model.proposals || []; if (!proposals.length) {{ $('proposals').innerHTML = '<p class="muted">No decision proposals are waiting for review.</p>'; return; }} $('proposals').innerHTML = proposals.map((p) => `<details><summary>${{esc(p.proposal_id)}} / ${{esc(p.status)}}</summary><p><b>${{esc(p.title || p.decision_id)}}</b></p><p class="muted">Derived from ${{esc(p.artifact_path || 'engineering artifact')}} · ${{esc(p.artifact_type || '')}}</p><blockquote>${{esc(p.source_sentence || 'No source sentence recorded.')}}</blockquote><p class="muted">${{esc(p.rationale || '')}}</p>${{p.status === 'PENDING' ? '<button data-proposal-action="confirm-proposal" class="safe">CONFIRM PROPOSAL</button><button data-proposal-action="reject-proposal" class="danger">REJECT PROPOSAL</button>' : `<span class="value">${{esc(p.status)}}${{p.confirmed_by ? ' by ' + esc(p.confirmed_by) : ''}}</span>`}}</details>`).join(''); document.querySelectorAll('[data-proposal-action]').forEach((button) => button.addEventListener('click', () => action(button.dataset.proposalAction))); }}
function renderMemory() {{ const comparison = model.memory_comparison; if (!comparison) {{ $('memoryComparison').innerHTML = '<div class="metric"><div class="label">Ready to run</div><div class="value">Backend ablation pending</div><p class="muted">Run the memory proof to compare the same review with and without remembered intent.</p></div>'; return; }} const on = comparison.memory_on || {{}}; const off = comparison.memory_removed || {{}}; $('memoryComparison').innerHTML = `<div class="comparison-grid"><div class="comparison-head"></div><div class="comparison-head">MEMORY PRESENT</div><div class="comparison-head">MEMORY REMOVED</div><div class="comparison-label">External fact</div><div class="metric">${{esc(on.current_fact)}} days</div><div class="metric">${{esc(off.current_fact)}} days</div><div class="comparison-label">Decision found</div><div class="metric">${{esc(on.decision_found || 'None')}}</div><div class="metric">${{esc(off.decision_found || 'None')}}</div><div class="comparison-label">Original assumption</div><div class="metric">${{esc(on.assumption || 'Missing')}}</div><div class="metric">${{esc(off.assumption || 'Missing')}}</div><div class="comparison-label">Expiry identified</div><div class="metric ${{on.expiry_detected ? 'blocked' : 'stands'}}">${{on.expiry_detected ? 'Yes' : 'No'}}</div><div class="metric">No</div><div class="comparison-label">Protection</div><div class="metric ${{on.protection === 'BLOCK' ? 'blocked' : 'allow'}}">${{esc(on.protection)}}</div><div class="metric unknown">${{esc(off.protection)}}</div></div><p class="muted" style="margin-top:16px">${{esc(comparison.conclusion || '')}}</p>`; }}
function renderWaivers() {{ const waivers = model.waivers || []; if (!waivers.length) {{ $('waivers').innerHTML = '<p class="muted">No human waiver is recorded. A non-standing result remains blocked.</p>'; return; }} $('waivers').innerHTML = waivers.map((w) => `<div class="metric"><div class="label">${{esc(w.status || 'WAIVER')}}</div><div class="value">${{esc(w.waiver_id || 'Not recorded')}} · ${{esc(w.decision_id || 'Not recorded')}}</div><p class="muted">Approved by ${{esc(w.issued_by || 'Not recorded')}} · expires ${{esc(formatDate(w.expires_at))}} · ${{esc(w.reason || '')}}</p></div>`).join(''); }}
function renderRealWorld() {{ const proof = model.real_world || {{}}; const cases = proof.cases || []; const evaluation = model.evaluation || {{}}; const statusClass = proof.status === 'REVIEWED' ? 'stands' : 'unknown'; $('realWorld').innerHTML = `<div class="grid"><div class="metric"><div class="label">Review status</div><div class="value ${{statusClass}}">${{esc(proof.status || 'PENDING')}}</div></div><div class="metric"><div class="label">Public cases</div><div class="value">${{esc(proof.reviewed_case_count ?? 0)}}</div></div><div class="metric"><div class="label">Controlled scenarios</div><div class="value">${{esc(evaluation.controlled_scenarios ?? 0)}}</div></div></div><div class="disclosure">Real-world evidence is reported separately from the controlled scenario. No benchmark score is claimed until all prediction artifacts are recorded.</div>${{cases.length ? cases.map((c) => `<details><summary>${{esc(c.case_id)}} · ${{esc(c.review_status || 'PENDING HUMAN REVIEW')}}</summary><p class="muted">${{esc(c.repository || '')}}</p><p><a href="${{esc(c.decision_url)}}" target="_blank" rel="noreferrer">Decision artifact ↗</a> · <a href="${{esc(c.historical_ground_truth_url)}}" target="_blank" rel="noreferrer">Historical source ↗</a> · <a href="${{esc(c.current_ground_truth_url)}}" target="_blank" rel="noreferrer">Current source ↗</a></p><p class="muted">${{esc(c.disclosure || '')}}</p></details>`).join('') : '<p class="muted">No source-linked public case is recorded.</p>'}}`; }}
function renderPartnerProof() {{ const proof = model.partner_proof || {{}}; const agents = proof.agents || []; $('partnerProof').innerHTML = `<p>${{esc(proof.summary || 'No completed verification record is available.')}}</p><div class="chain"><div class="chain-step"><div class="label">01 · Virtuals ACP</div><strong>Job ${{esc(proof.acp_job_id || 'Not recorded')}} · completed</strong><span><a href="${{esc(proof.acp_job_url || '#')}}" target="_blank" rel="noreferrer">Open public ACP scan ↗</a><br>Authenticated job record retained below.</span></div><div class="chain-step"><div class="label">02 · Verifier</div><strong>Source extracted</strong><span>Typed value returned with extraction provenance.</span></div><div class="chain-step"><div class="label">03 · Base EAS</div><strong>Observation recorded</strong><span><a href="${{esc(proof.eas_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open Base transaction ↗</a></span></div><div class="chain-step"><div class="label">04 · Sibyl</div><strong>Read back and stored</strong><span>Condition reference and standing journal updated.</span></div><div class="chain-step"><div class="label">05 · ERC-8004</div><strong>Outcome recorded</strong><span><a href="${{esc(proof.erc8004_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open feedback ↗</a></span></div></div><div class="metric" style="margin-top:18px"><div class="label">Registered agent identities</div><div class="value">${{agents.length}} Virtuals profiles</div><p>${{agents.map((agent) => `<span style="display:block;margin-top:8px"><b>${{esc(agent.name)}}</b> · ${{esc(agent.role)}} · profile <code>${{esc(agent.virtual_agent_id)}}</code></span>`).join('')}}</p><p><a href="${{esc(proof.acp_directory_url || '#')}}" target="_blank" rel="noreferrer">Open agent directory ↗</a> · <a href="${{esc(proof.acp_scan_url || '#')}}" target="_blank" rel="noreferrer">Open ACP scan ↗</a></p><p class="muted">Registry profile IDs are displayed as identities; no ACP Entity ID is inferred from them.</p></div><details><summary>Evidence identity</summary><pre>${{esc(JSON.stringify({{eas_uid: proof.eas_uid, acp_job_id: proof.acp_job_id, acp_api_record: proof.acp_api_url, erc8004_agent_id: proof.erc8004_agent_id}}, null, 2))}}</pre><p class="muted">The ACP API record requires platform credentials and returns HTTP 401 to anonymous visitors.</p></details>`; }}
function renderProvenance(finding) {{ const rows = allObservations(finding); $('provenance').innerHTML = rows.length ? rows.map((x) => `<details><summary>${{esc(x.observation_uid)}} · ${{esc(x.value)}} ${{esc(x.unit || '')}}</summary><div class="provenance-row"><div class="label">Value</div><div>${{esc(x.value)}} ${{esc(x.unit || '')}}</div></div><div class="provenance-row"><div class="label">Effective</div><div>${{formatDate(x.effective_from)}}</div></div><div class="provenance-row"><div class="label">Observed / recorded</div><div>${{formatDate(x.observed_at)}} / ${{formatDate(x.recorded_at)}}</div></div><div class="provenance-row"><div class="label">Source</div><div><a href="${{esc(x.source_url || '#')}}" target="_blank" rel="noreferrer">${{esc(x.source_url || 'not recorded')}} ↗</a></div></div><div class="provenance-row"><div class="label">Extraction</div><div><code>${{esc(x.extraction_method || 'Not recorded')}} · ${{esc(x.extraction_version || 'Not recorded')}}</code></div></div><div class="provenance-row"><div class="label">Evidence hash</div><div><code>${{esc(x.evidence_hash || 'Not recorded')}}</code></div></div><p class="muted">${{esc(x.notes || '')}}</p><details><summary>View raw record</summary><pre>${{esc(JSON.stringify(x, null, 2))}}</pre></details></details>`).join('') : '<p class="muted">No temporal observations are recorded.</p>'; }}
function renderActivity() {{ const rows = model.activity || []; $('activityLog').innerHTML = rows.length ? rows.map((row) => `<div class="activity-row"><div class="activity-time">${{esc(row.timestamp || 'journal time')}}</div><div class="activity-event">${{esc(row.event || 'journal event')}}</div><div><b>${{esc(row.decision_id || 'Standing')}}</b><div class="muted">${{esc(row.detail || '')}}</div></div></div>`).join('') : '<p class="muted">No activity has been recorded yet.</p>'; }}
async function action(name) {{ try {{ const response = await fetch('/api/sandbox/' + name, {{method:'POST'}}); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'action failed'); if (name === 'waiver') {{ $('actionResult').textContent = body.disclosure + ' ' + body.status; setView('sandbox'); return; }} model = body; selectedTime = null; const messages = {{'break':'Controlled source changed: 365 → 90 days; the backend re-evaluated ACME-001.','reset':'Sandbox reset: ACME-001 is standing again.','resolve':'ACME-001 superseded by STORAGE-002.','confirm-proposal':'Human confirmation recorded; the proposal is now a decision.','reject-proposal':'Human rejection recorded; no decision was created.','review':'Backend review completed.','memory-comparison':'Memory proof completed against a fresh store.'}}; $('actionResult').textContent = messages[name] || 'Action completed.'; if (name === 'memory-comparison') setView('evidence'); else if (name === 'review') setView('reviews'); render(); }} catch (error) {{ $('actionResult').textContent = String(error); }} }}
document.querySelectorAll('[data-view]').forEach((item) => item.addEventListener('click', (event) => {{ if (item.tagName.toLowerCase() !== 'a' || item.getAttribute('href')?.startsWith('/console')) event.preventDefault(); setView(item.dataset.view); }})); $('timeSlider').addEventListener('input', () => {{ selectedTime = Number($('timeSlider').value); render(); }}); $('memoryCompare').addEventListener('click', () => action('memory-comparison')); $('break').addEventListener('click', () => action('break')); $('restore').addEventListener('click', () => action('reset')); $('resolve').addEventListener('click', () => action('resolve')); $('reviewAgain').addEventListener('click', () => action('review')); $('waiver').addEventListener('click', () => action('waiver')); render();
</script>
</body>
</html>'''


def serve_dashboard(app: DashboardApp, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Serve the Standing product surface and controlled-scenario endpoints."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "Standing"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/favicon.svg":
                    _respond_svg(self, FAVICON_SVG)
                elif parsed.path == "/":
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
                elif parsed.path.startswith("/console/decisions/"):
                    decision_id = unquote(parsed.path[len("/console/decisions/"):]).strip("/")
                    exists = any(
                        item.get("decision_id") == decision_id
                        for item in app.state()["decisions"]
                    )
                    if not decision_id or not exists:
                        _respond_json(self, {"error": "decision not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        _respond_html(self, render_dashboard_html(app.state()))
                elif parsed.path.startswith("/console/evidence/"):
                    evidence_id = unquote(parsed.path[len("/console/evidence/"):]).strip("/")
                    state = app.state()
                    condition_exists = bool(evidence_id and app.tools.condition_history(evidence_id))
                    observation_exists = any(
                        observation.get("observation_uid") == evidence_id
                        for decision in state["decisions"]
                        for condition in decision.get("conditions", [])
                        for observation in condition.get("observations", [])
                    )
                    if not condition_exists and not observation_exists:
                        _respond_json(self, {"error": "evidence not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        _respond_html(self, render_dashboard_html(state))
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
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(encoded)


def _respond_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    encoded = html.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("content-type", "text/html; charset=utf-8")
    handler.send_header("content-length", str(len(encoded)))
    handler.send_header("cache-control", "no-store")
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(encoded)


def _respond_svg(handler: BaseHTTPRequestHandler, svg: str) -> None:
    encoded = svg.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("content-type", "image/svg+xml")
    handler.send_header("content-length", str(len(encoded)))
    handler.send_header("cache-control", "public, max-age=86400")
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(encoded)


def _send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    """Apply a narrow browser policy to every public response."""

    handler.send_header("x-content-type-options", "nosniff")
    handler.send_header("x-frame-options", "DENY")
    handler.send_header("referrer-policy", "no-referrer")
    handler.send_header("permissions-policy", "camera=(), microphone=(), geolocation=()")
    handler.send_header(
        "content-security-policy",
        "default-src 'self'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'; "
        "img-src 'self' data:; object-src 'none'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'",
    )
