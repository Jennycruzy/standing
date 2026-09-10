"""Disclosure-first interactive dashboard and constrained demo controller."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from sibyl_memory_client.exceptions import NotFoundError  # type: ignore[import-untyped]

from .memory import MemoryStore
from .model_review import DecisionProposal
from .reviewer import ReviewerToolError, ReviewerTools
from .temporal import TemporalObservationError, observation_evidence_hash, parse_timestamp


CONTROLLED_DISCLOSURE = (
    "CONTROLLED DEMO — Fictional Acme Corporation. "
    "Source operated by Standing for deterministic demonstration; not vendor evidence."
)
DEMO_CONDITION = "sandbox.demo.retention_days"
DEMO_PATH = "src/archive.py"
DEMO_SOURCE_URL = "https://raw.githubusercontent.com/Jennycruzy/standing/main/docs/demo/acme-retention.json"
DEMO_PROPOSAL_ARTIFACT = "docs/decisions/0001-acp-adapter.md"
DEMO_EFFECTIVE_INITIAL = 1767225600  # 2026-01-01T00:00:00Z
DEMO_EFFECTIVE_CHANGED = 1788739200  # 2026-09-07T00:00:00Z
EVALUATION_CASES_PATH = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "cases.json"
PARTNER_PROOF = {
    "acp_job_id": "77748",
    "acp_job_url": "https://api.acp.virtuals.io/jobs/8453/77748",
    "eas_uid": "0x70675af1277c400c155de2e32684cfb264be8061578fb9afa17c6fcdd001bf5e",
    "eas_transaction_url": "https://basescan.org/tx/0xfa23b10158da3723d28508d51c8acd6916696cd0a609e4fce741c989e5573eff",
    "erc8004_transaction_url": "https://basescan.org/tx/0xb12f670d1c643556b7bb6c45cec12462f9c7f7e41775681b4c1f9b0278146954",
    "summary": "Completed ACP verification → Base EAS observation → Sibyl update → ERC-8004 feedback",
}


@dataclass
class DemoController:
    """A fixed, local-only controller for the public demo buttons."""

    store: MemoryStore
    tools: ReviewerTools

    @classmethod
    def create(cls, store: MemoryStore) -> DemoController:
        controller = cls(store, ReviewerTools(store))
        controller.seed()
        return controller

    def seed(self) -> None:
        """Create the pre-authored initial demo state in the supplied store."""

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
                "governed_paths": [DEMO_PATH, "infra/acme.tf"],
                "conditions": [
                    {
                        "condition_key": DEMO_CONDITION,
                        "predicate": "retention_days >= 365",
                        "provenance": "CONFIRMED",
                        "required": True,
                    }
                ],
            },
        )
        initial = _demo_observation(
            "demo-initial",
            365,
            DEMO_EFFECTIVE_INITIAL,
            "2026-02-11",
        )
        self.tools.record_temporal_observation(initial)
        self._save_demo_reference(initial)
        evaluation = self.tools.evaluate_standing("ACME-001")
        self.tools.write_standing_change(
            "ACME-001",
            evaluation,
            action="allow",
            explanation="Initial controlled demo decision was human-approved.",
        )
        self.tools.record_decision_proposal(
            DecisionProposal(
                decision_id="AUDIT-003",
                title="Keep an audit trail for archive changes",
                description="A non-blocking proposal retained to demonstrate confirmation workflow.",
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
                artifact_path=DEMO_PROPOSAL_ARTIFACT,
                artifact_type="DESIGN_DOCUMENT",
                artifact_sha256="d" * 64,
                source_sentence="A controlled pending proposal demonstrates human confirmation.",
                rationale="This fixed proposal is informational and cannot block until a human confirms it.",
                model_id="standing-demo-model",
            )
        )

    def break_assumption(self) -> None:
        self._ensure_decision()
        observation = _demo_observation("demo-changed", 90, DEMO_EFFECTIVE_CHANGED, "2026-09-07")
        if not any(item.get("observation_uid") == observation["observation_uid"] for item in self.tools.read_observations(DEMO_CONDITION)):
            self.tools.record_temporal_observation(observation)
        self._save_demo_reference(observation)
        evaluation = self.tools.evaluate_standing("ACME-001")
        if evaluation.state.value != "STANDS":
            self.tools.write_standing_change(
                "ACME-001",
                evaluation,
                action="block",
                explanation="The fixed controlled source changed from 365 to 90 days.",
            )

    def restore(self) -> None:
        self._ensure_decision()
        observation = _demo_observation("demo-restored", 365, int(time()), "2026-09-09")
        self.tools.record_temporal_observation(observation)
        self._save_demo_reference(observation)
        evaluation = self.tools.evaluate_standing("ACME-001")
        self.tools.write_standing_change(
            "ACME-001",
            evaluation,
            action="allow",
            explanation="The fixed controlled demo source was restored to 365 days.",
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
                "governed_paths": [DEMO_PATH, "infra/contoso.tf"],
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
                "accepted_source_url": "https://controlled-demo.invalid/contoso",
                "observation_uids": ["controlled-contoso-demo"],
                "basis": "fixed replacement decision demo",
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
        proposal = self._pending_demo_proposal()
        self.tools.confirm_decision_proposal(
            proposal,
            confirmed_by="demo-human",
            confirmation_note="Human reviewed the displayed source sentence and confirmed this proposal.",
            confirmed_at=int(time()),
        )

    def reject_proposal(self) -> None:
        proposal = self._pending_demo_proposal()
        self.tools.reject_decision_proposal(
            proposal,
            rejected_by="demo-human",
            reason="Human rejected the displayed proposal for this demo run.",
            rejected_at=int(time()),
        )

    def waiver_preview(self) -> dict[str, Any]:
        return {
            "status": "PREVIEW ONLY",
            "disclosure": "No waiver is issued by this dashboard action.",
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
            raise ReviewerToolError("controlled demo decision is not available") from error

    def _pending_demo_proposal(self) -> str:
        for entity in self.store.list_decision_proposals():
            body = _entity_body(entity)
            if body.get("status") == "PENDING":
                proposal_id = entity.get("key", entity.get("name"))
                if isinstance(proposal_id, str) and proposal_id.strip():
                    return proposal_id
        raise ReviewerToolError("no pending controlled demo proposal is available")

    def _save_demo_reference(self, observation: Mapping[str, Any]) -> None:
        self.store.save_condition_reference(
            DEMO_CONDITION,
            {
                "condition_key": DEMO_CONDITION,
                "accepted_value": observation["value"],
                "value_type": "number",
                "unit": "days",
                "effective_from": observation["effective_from"],
                "accepted_at": observation["recorded_at"],
                "last_verified_at": observation["recorded_at"],
                "accepted_source_url": DEMO_SOURCE_URL,
                "observation_uids": [observation["observation_uid"]],
                "basis": "controlled demo source extraction",
                "status": "ACCEPTED",
                "evidence_fresh": True,
                "demo_controlled": True,
            },
            metadata={"demo_controlled": True, "source_url": DEMO_SOURCE_URL},
        )


class DashboardApp:
    """Small HTTP application used by the local dashboard command."""

    def __init__(self, store: MemoryStore, *, demo: bool) -> None:
        self.store = store
        self.tools = ReviewerTools(store)
        self.demo = demo
        self.controller = DemoController.create(store) if demo else None

    def state(self) -> dict[str, Any]:
        return build_dashboard_payload(self.tools, demo=self.demo)

    def source(self) -> dict[str, Any]:
        payload = self.state()
        demo = payload["demo"]
        if not isinstance(demo, dict):
            raise ReviewerToolError("dashboard demo payload is invalid")
        return {
            "vendor": "Fictional Acme Corporation",
            "condition_key": DEMO_CONDITION,
            "retention_days": demo["current_value"],
            "disclosure": CONTROLLED_DISCLOSURE,
            "demo_controlled": True,
        }

    def action(self, name: str) -> dict[str, Any]:
        if not self.demo or self.controller is None:
            raise ReviewerToolError("demo actions are disabled outside --demo mode")
        if name == "break":
            self.controller.break_assumption()
        elif name == "restore":
            self.controller.restore()
        elif name == "resolve":
            self.controller.resolve()
        elif name == "confirm-proposal":
            self.controller.confirm_proposal()
        elif name == "reject-proposal":
            self.controller.reject_proposal()
        elif name == "waiver":
            return self.controller.waiver_preview()
        elif name == "review":
            pass
        else:
            raise ReviewerToolError("unknown fixed dashboard action")
        return self.state()


def build_dashboard_payload(tools: ReviewerTools, *, demo: bool = False) -> dict[str, Any]:
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
    demo_conditions = all_conditions.get(DEMO_CONDITION, {})
    current_value = 365
    if isinstance(demo_conditions, Mapping):
        reference = demo_conditions.get("reference")
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
    return {
        "controlled_demo": demo,
        "disclosure": CONTROLLED_DISCLOSURE if demo else None,
        "summary": (
            f"{len(findings)} engineering decision(s) no longer have standing."
            if findings
            else "All remembered engineering decisions currently have standing."
        ),
        "primary_finding": primary,
        "decisions": decision_payloads,
        "proposals": proposals,
        "waivers": waivers,
        "real_world": _real_world_payload(),
        "partner_proof": dict(PARTNER_PROOF),
        "demo": {
            "condition_key": DEMO_CONDITION,
            "source_url": DEMO_SOURCE_URL,
            "current_value": current_value,
            "initial_value": 365,
            "changed_value": 90,
            "disclosure": CONTROLLED_DISCLOSURE,
            "timeline": {
                "decision_date": DEMO_EFFECTIVE_INITIAL,
                "change_date": DEMO_EFFECTIVE_CHANGED,
                "now": int(time()),
            },
        },
    }


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
        "disclosure": "Real-world and controlled evidence are kept separate; pending candidates are not product claims.",
    }


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
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #09111f; color: #e5edf8; }}
    body {{ margin: 0; background: radial-gradient(circle at top right, #152b49, #09111f 55%); min-height: 100vh; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 28px; }}
    .eyebrow {{ color: #8ca9c9; text-transform: uppercase; letter-spacing: .14em; font-size: .72rem; font-weight: 800; }}
    h1, h2, h3 {{ margin: .35rem 0 .8rem; }}
    h1 {{ font-size: clamp(2rem, 5vw, 4.5rem); max-width: 850px; line-height: .98; }}
    h2 {{ font-size: 1.25rem; }}
    .muted {{ color: #91a4bc; }}
    .disclosure {{ border: 1px solid #db9b35; background: #30220d; color: #ffd78a; padding: 12px 15px; border-radius: 10px; font-weight: 700; margin: 14px 0; }}
    .card {{ background: rgba(16, 29, 49, .92); border: 1px solid #263e5d; border-radius: 16px; padding: 20px; margin-top: 16px; box-shadow: 0 15px 50px rgba(0,0,0,.16); }}
    .finding {{ border-color: #bb3d55; background: linear-gradient(135deg, rgba(84, 24, 43, .92), rgba(16, 29, 49, .95)); }}
    .finding.stands {{ border-color: #267d68; background: linear-gradient(135deg, rgba(17, 67, 58, .9), rgba(16, 29, 49, .95)); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .metric {{ background: #0b1729; border: 1px solid #203752; border-radius: 10px; padding: 13px; }}
    .label {{ color: #8ca9c9; text-transform: uppercase; letter-spacing: .08em; font-size: .68rem; font-weight: 800; }}
    .value {{ margin-top: 5px; font-size: 1.15rem; font-weight: 800; overflow-wrap: anywhere; }}
    .expired, .blocked {{ color: #ff8090; }} .stands, .allow {{ color: #70e0bd; }} .unknown, .contested {{ color: #ffd78a; }}
    button {{ border: 1px solid #3d6590; border-radius: 8px; background: #173458; color: #f0f6ff; padding: 9px 12px; cursor: pointer; font-weight: 750; margin: 4px 4px 0 0; }}
    button:hover {{ background: #235181; }} button.danger {{ border-color: #bb3d55; background: #64243a; }} button.safe {{ border-color: #267d68; background: #145342; }}
    .toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }}
    .graph {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
    .node {{ padding: 12px; background: #10223a; border: 1px solid #3a5b80; border-radius: 10px; min-width: 120px; }}
    button.node {{ text-align: left; color: #e5edf8; font: inherit; }}
    button.node:focus-visible {{ outline: 2px solid #70e0bd; outline-offset: 2px; }}
    .arrow {{ color: #7591b2; font-size: 1.3rem; }}
    .timeline {{ width: 100%; accent-color: #70e0bd; }}
    .timeline-row {{ display: flex; justify-content: space-between; color: #8ca9c9; font-size: .8rem; }}
    details {{ border-top: 1px solid #263e5d; padding: 10px 0; }} summary {{ cursor: pointer; font-weight: 750; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; color: #b8cbe1; font-size: .78rem; }}
    table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; padding: 9px; border-bottom: 1px solid #263e5d; vertical-align: top; }} th {{ color: #8ca9c9; font-size: .7rem; text-transform: uppercase; }}
    .off {{ opacity: .58; }}
  </style>
</head>
<body>
<main>
  <div class="eyebrow">Standing / temporal engineering intent</div>
  <h1 id="summary">Loading remembered reasoning…</h1>
  <div id="disclosure"></div>
  <section id="finding" class="card finding"></section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Decision graph</h2><span class="muted">Code → decision → assumption → evidence → standing</span></div>
    <div id="graph" class="graph"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Bitemporal time travel</h2><span id="selectedDate" class="muted"></span></div>
    <input id="timeSlider" class="timeline" type="range" min="0" max="1" value="1" step="1">
    <div class="timeline-row"><span>Decision made</span><span>World changed</span><span>Today</span></div>
    <div id="timeTravel" class="grid" style="margin-top:12px"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Interactive PR review</h2><span id="reviewResult" class="muted"></span></div>
    <p class="muted">The review uses the exact stored governed path. Full-text matches alone never block.</p>
    <div id="prReview"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Human confirmation</h2><span class="muted">Model proposals never govern code automatically</span></div>
    <div id="proposals"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Memory comparison</h2><button id="memoryToggle">MEMORY OFF</button></div>
    <div id="memoryComparison"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Waiver status</h2><span class="muted">Human-issued, temporary, and automatically expiring</span></div>
    <div id="waivers"></div>
  </section>
  <section class="card">
    <div class="toolbar"><h2 style="margin-right:auto">Controlled demo controls</h2><span class="muted">Fixed local workflow; no arbitrary signing</span></div>
    <div class="disclosure">{escape(CONTROLLED_DISCLOSURE)}</div>
    <div class="toolbar">
      <button id="break" class="danger">BREAK DEMO ASSUMPTION</button>
      <button id="restore" class="safe">RESTORE DEMO</button>
      <button id="resolve" class="safe">RECORD REPLACEMENT DECISION</button>
      <button id="reviewAgain">RUN REVIEW AGAIN</button>
      <button id="waiver">INSPECT DEMO WAIVER</button>
    </div>
    <div id="actionResult" class="muted" style="margin-top:10px"></div>
  </section>
  <section class="card"><h2>Real-world proof</h2><div id="realWorld"></div></section>
  <section class="card"><h2>Live partner proof</h2><div id="partnerProof"></div></section>
  <section class="card"><h2>Evidence provenance</h2><div id="provenance"></div></section>
</main>
<script>
const initial = {encoded};
let model = initial;
let memoryOn = true;
let selectedTime = null;
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const formatDate = (seconds) => seconds ? new Date(Number(seconds) * 1000).toISOString().slice(0,10) : '—';
const primary = () => model.primary_finding;
function render() {{
  $('summary').textContent = model.summary || 'Standing';
  $('disclosure').innerHTML = model.disclosure ? `<div class="disclosure">${{esc(model.disclosure)}}</div>` : '';
  const finding = primary();
  if (!finding) {{ $('finding').innerHTML = '<h2>No remembered decisions</h2><p class="muted">Standing has no engineering intent to evaluate yet.</p>'; $('finding').className = 'card finding stands'; }}
  else {{
    const ev = finding.evaluation || {{}}; const condition = (ev.conditions || [])[0] || {{}};
    $('finding').className = 'card finding ' + String(ev.state || '').toLowerCase();
    $('finding').innerHTML = `<div class="eyebrow">Primary engineering finding</div><h2>${{esc(finding.body.title || finding.decision_id)}}</h2><div class="grid"><div class="metric"><div class="label">Decision</div><div class="value">${{esc(finding.decision_id)}}</div></div><div class="metric"><div class="label">Required</div><div class="value">${{esc(condition.predicate || '—')}}</div></div><div class="metric"><div class="label">Current</div><div class="value">${{esc(condition.accepted_value ?? 'unknown')}}</div></div><div class="metric"><div class="label">Affected</div><div class="value">${{(finding.body.governed_paths || []).length}} files</div></div><div class="metric"><div class="label">Status</div><div class="value ${{String(ev.state || '').toLowerCase()}}">${{esc(ev.state || 'UNKNOWN')}}</div></div></div><p class="muted">${{esc(finding.body.description || '')}}</p>`;
  }}
  renderGraph(finding); renderTimeTravel(finding); renderPr(finding); renderProposals(); renderMemory(finding); renderWaivers(); renderRealWorld(); renderPartnerProof(); renderProvenance(finding);
}}
function renderGraph(finding) {{
  if (!finding) {{ $('graph').innerHTML = '<span class="muted">No graph available.</span>'; return; }}
  const condition = (finding.conditions || [])[0] || {{}}; const observations = condition.observations || []; const ref = condition.reference || {{}}; const state = (finding.evaluation || {{}}).state || 'UNKNOWN';
  const node = (target, label, value, className = '') => `<button type="button" class="node ${{className}}" data-graph-target="${{esc(target)}}"><div class="label">${{esc(label)}}</div><b>${{esc(value)}}</b></button>`;
  $('graph').innerHTML = [node('code', 'Code', (finding.body.governed_paths || [])[0] || '—'),`<span class="arrow">↓</span>`,node('decision', 'Decision', finding.decision_id),`<span class="arrow">↓</span>`,node('assumption', 'Assumption', condition.rule?.predicate || '—'),`<span class="arrow">↓</span>`,node('evidence', 'Accepted evidence', `${{observations.length}} observation(s)`),`<span class="arrow">↓</span>`,node('standing', 'Standing', state, String(state).toLowerCase())].join('');
  document.querySelectorAll('[data-graph-target]').forEach((element) => element.addEventListener('click', () => {{
    const target = element.dataset.graphTarget;
    const section = target === 'code' ? 'prReview' : target === 'evidence' ? 'provenance' : target === 'assumption' ? 'finding' : target === 'standing' ? 'finding' : 'finding';
    $(section).scrollIntoView({{behavior: 'smooth', block: 'center'}});
    $('actionResult').textContent = `Selected ${{target}} in the decision graph.`;
  }}));
}}
function allObservations(finding) {{ return ((finding?.conditions || [])[0]?.observations || []).filter((x) => x && x.effective_from != null); }}
function renderTimeTravel(finding) {{
  const rows = allObservations(finding); const demo = model.demo || {{}}; const points = [...new Set(rows.map((x) => Number(x.effective_from)).concat([demo.timeline?.decision_date, demo.timeline?.change_date, demo.timeline?.now].filter(Boolean)))].sort((a,b)=>a-b); const slider = $('timeSlider'); slider.max = String(Math.max(1, points.length - 1)); slider.value = String(selectedTime == null ? points.length - 1 : Math.min(selectedTime, points.length - 1)); const point = points[Number(slider.value)] || Math.floor(Date.now()/1000); selectedTime = Number(slider.value); $('selectedDate').textContent = `Selected: ${{formatDate(point)}}`;
  const valid = rows.filter((x) => Number(x.effective_from) <= point).sort((a,b) => Number(b.effective_from)-Number(a.effective_from))[0]; const known = rows.filter((x) => Number(x.recorded_at ?? Infinity) <= point && Number(x.effective_from) <= point).sort((a,b) => Number(b.effective_from)-Number(a.effective_from))[0];
  $('timeTravel').innerHTML = `<div class="metric"><div class="label">What we now believe was true</div><div class="value">${{esc(valid?.value ?? 'unknown')}} ${{esc(valid?.unit || '')}}</div><p class="muted">Valid time: ${{formatDate(valid?.effective_from)}}</p></div><div class="metric"><div class="label">What Standing knew then</div><div class="value">${{esc(known?.value ?? 'not recorded')}}</div><p class="muted">Knowledge cutoff: ${{formatDate(point)}}</p></div><div class="metric"><div class="label">Assessment</div><div class="value">${{valid && known && valid.value !== known.value ? 'Justified from available evidence' : 'Evidence and knowledge align'}}</div><p class="muted">Standing never rewrites the original record.</p></div>`;
}}
function renderPr(finding) {{ const paths = finding?.body?.governed_paths || []; const hit = paths.includes('src/archive.py') || paths.some((p) => 'src/archive.py'.startsWith(String(p).replace('/**','/'))); $('reviewResult').textContent = finding ? (hit ? `${{finding.decision_id}} governs the selected path` : 'No exact governed-path match') : 'No decision found'; $('prReview').innerHTML = `<div class="metric"><div class="label">PR #12 / changed path</div><div class="value">src/archive.py</div><p class="muted">${{hit ? `Result: ${{(finding.evaluation || {{}}).state === 'STANDS' ? 'ALLOW' : 'BLOCK'}}` : 'Historical protection unavailable'}}</p></div>`; }}
function renderProposals() {{ const proposals = model.proposals || []; if (!proposals.length) {{ $('proposals').innerHTML = '<p class="muted">No decision proposals are waiting for review.</p>'; return; }} $('proposals').innerHTML = proposals.map((p) => `<details><summary>${{esc(p.proposal_id)}} — ${{esc(p.status)}}</summary><p><b>${{esc(p.title || p.decision_id)}}</b></p><p class="muted">Derived from ${{esc(p.artifact_path || 'engineering artifact')}} · ${{esc(p.artifact_type || '')}}</p><blockquote>${{esc(p.source_sentence || 'No source sentence recorded.')}}</blockquote><p class="muted">${{esc(p.rationale || '')}}</p>${{p.status === 'PENDING' ? '<button data-proposal-action="confirm-proposal" class="safe">CONFIRM PROPOSAL</button><button data-proposal-action="reject-proposal" class="danger">REJECT PROPOSAL</button>' : `<span class="value">${{esc(p.status)}}${{p.confirmed_by ? ' by ' + esc(p.confirmed_by) : ''}}</span>`}}</details>`).join(''); document.querySelectorAll('[data-proposal-action]').forEach((button) => button.addEventListener('click', () => action(button.dataset.proposalAction))); }}
function renderMemory(finding) {{ if (!memoryOn) {{ $('memoryComparison').innerHTML = `<div class="grid"><div class="metric"><div class="label">External fact</div><div class="value">${{esc(model.demo?.current_value ?? 'unknown')}} days</div></div><div class="metric"><div class="label">Governing decision</div><div class="value">None</div></div><div class="metric"><div class="label">Original assumption</div><div class="value">Missing</div></div><div class="metric"><div class="label">Protection</div><div class="value unknown">Historical protection unavailable</div></div></div>`; return; }} $('memoryComparison').innerHTML = `<div class="grid"><div class="metric"><div class="label">Memory ON</div><div class="value">${{esc(finding?.decision_id || 'None')}}</div></div><div class="metric"><div class="label">Assumption recovered</div><div class="value">${{esc((finding?.conditions || [])[0]?.rule?.predicate || 'None')}}</div></div><div class="metric"><div class="label">Expiry detected</div><div class="value ${{finding && finding.evaluation?.state !== 'STANDS' ? 'blocked' : 'stands'}}">${{finding && finding.evaluation?.state !== 'STANDS' ? 'Yes' : 'No'}}</div></div><div class="metric"><div class="label">Protection</div><div class="value">${{finding && finding.evaluation?.state !== 'STANDS' ? 'BLOCK' : 'ALLOW'}}</div></div></div>`; }}
function renderWaivers() {{ const waivers = model.waivers || []; if (!waivers.length) {{ $('waivers').innerHTML = '<p class="muted">No human waiver is recorded. A non-standing result remains blocked.</p>'; return; }} $('waivers').innerHTML = waivers.map((w) => `<div class="metric"><div class="label">${{esc(w.status || 'WAIVER')}}</div><div class="value">${{esc(w.waiver_id || '—')}} · ${{esc(w.decision_id || '—')}}</div><p class="muted">Approved by ${{esc(w.issued_by || '—')}} · expires ${{esc(formatDate(w.expires_at))}} · ${{esc(w.reason || '')}}</p></div>`).join(''); }}
function renderRealWorld() {{ const proof = model.real_world || {{}}; const cases = proof.cases || []; $('realWorld').innerHTML = `<div class="grid"><div class="metric"><div class="label">Status</div><div class="value unknown">${{esc(proof.status || 'PENDING')}}</div></div><div class="metric"><div class="label">Reviewed cases</div><div class="value">${{esc(proof.reviewed_case_count ?? 0)}}</div></div><div class="metric"><div class="label">Pending candidates</div><div class="value">${{esc(proof.pending_case_count ?? cases.length)}}</div></div></div>${{cases.length ? cases.map((c) => `<details><summary>${{esc(c.case_id)}} — ${{esc(c.review_status || 'PENDING HUMAN REVIEW')}}</summary><p class="muted">${{esc(c.repository || '')}}</p><p><a href="${{esc(c.decision_url)}}" target="_blank" rel="noreferrer">Decision artifact</a> · <a href="${{esc(c.historical_ground_truth_url)}}" target="_blank" rel="noreferrer">Historical source</a> · <a href="${{esc(c.current_ground_truth_url)}}" target="_blank" rel="noreferrer">Current source</a></p><p class="muted">${{esc(c.disclosure || '')}}</p></details>`).join('') : '<p class="muted">No source-linked real-world candidate is recorded.</p>'}}`; }}
function renderPartnerProof() {{ const proof = model.partner_proof || {{}}; $('partnerProof').innerHTML = `<p>${{esc(proof.summary || 'No live partner proof recorded.')}}</p><div class="grid"><div class="metric"><div class="label">Virtuals ACP</div><div class="value">Job ${{esc(proof.acp_job_id || '—')}}</div><p><a href="${{esc(proof.acp_job_url || '#')}}" target="_blank" rel="noreferrer">Open completed job</a></p></div><div class="metric"><div class="label">Base EAS</div><div class="value">Observation recorded</div><p><a href="${{esc(proof.eas_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open Base transaction</a></p></div><div class="metric"><div class="label">ERC-8004</div><div class="value">Feedback recorded</div><p><a href="${{esc(proof.erc8004_transaction_url || '#')}}" target="_blank" rel="noreferrer">Open feedback transaction</a></p></div></div><details><summary>Evidence identity</summary><pre>${{esc(JSON.stringify({{eas_uid: proof.eas_uid, acp_job_id: proof.acp_job_id}}, null, 2))}}</pre></details>`; }}
function renderProvenance(finding) {{ const rows = allObservations(finding); $('provenance').innerHTML = rows.length ? rows.map((x) => `<details><summary>${{esc(x.observation_uid)}} — ${{esc(x.value)}} ${{esc(x.unit || '')}}</summary><pre>${{esc(JSON.stringify(x, null, 2))}}</pre></details>`).join('') : '<p class="muted">No temporal observations are recorded.</p>'; }}
async function action(name) {{ try {{ const response = await fetch('/api/demo/' + name, {{method:'POST'}}); const body = await response.json(); if (!response.ok) throw new Error(body.error || 'action failed'); if (name === 'waiver') {{ $('actionResult').textContent = body.disclosure + ' ' + body.status; return; }} model = body; selectedTime = null; $('actionResult').textContent = name === 'break' ? 'Controlled source changed: 365 → 90 days.' : name === 'restore' ? 'Controlled source restored: 90 → 365 days.' : name === 'resolve' ? 'ACME-001 superseded by STORAGE-002.' : name === 'confirm-proposal' ? 'Human confirmation recorded; the proposal is now a decision.' : name === 'reject-proposal' ? 'Human rejection recorded; no decision was created.' : 'Review completed.'; render(); }} catch (error) {{ $('actionResult').textContent = String(error); }} }}
$('timeSlider').addEventListener('input', () => {{ selectedTime = Number($('timeSlider').value); render(); }}); $('memoryToggle').addEventListener('click', () => {{ memoryOn = !memoryOn; $('memoryToggle').textContent = memoryOn ? 'MEMORY OFF' : 'MEMORY ON'; render(); }}); $('break').addEventListener('click', () => action('break')); $('restore').addEventListener('click', () => action('restore')); $('resolve').addEventListener('click', () => action('resolve')); $('reviewAgain').addEventListener('click', () => action('review')); $('waiver').addEventListener('click', () => action('waiver')); render();
</script>
</body>
</html>'''


def serve_dashboard(app: DashboardApp, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Serve the dashboard and its fixed demo endpoints."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    _respond_html(self, render_dashboard_html(app.state()))
                elif parsed.path == "/api/state":
                    _respond_json(self, app.state())
                elif parsed.path == "/api/demo-source":
                    _respond_json(self, app.source())
                else:
                    _respond_json(self, {"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except (OSError, ValueError, ReviewerToolError, TemporalObservationError) as error:
                _respond_json(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                prefix = "/api/demo/"
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
        server.serve_forever()
    finally:
        server.server_close()


def _demo_observation(uid: str, value: int, effective_from: int, recorded_date: str) -> dict[str, Any]:
    recorded_at = parse_timestamp(recorded_date, label="recorded_at")
    body: dict[str, Any] = {
        "condition_key": DEMO_CONDITION,
        "value": value,
        "value_type": "number",
        "unit": "days",
        "effective_from": effective_from,
        "observed_at": recorded_at,
        "recorded_at": recorded_at,
        "source_url": DEMO_SOURCE_URL,
        "source_domain": "raw.githubusercontent.com",
        "source_type": "vendor_primary",
        "attester": "standing-demo-attester",
        "operator_id": "standing-demo-operator",
        "extraction_method": "JSON_PATH",
        "extraction_version": "retention-json-v1",
        "observation_uid": uid,
        "evidence_hash": observation_evidence_hash(
            {"condition_key": DEMO_CONDITION, "value": value, "effective_from": effective_from}
        ),
        "notes": CONTROLLED_DISCLOSURE,
        "demo_controlled": True,
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
