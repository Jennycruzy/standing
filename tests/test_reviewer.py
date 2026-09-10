import tempfile
import hashlib
import unittest
from pathlib import Path

from sibyl_memory_client.exceptions import NotFoundError

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.artifacts import ArtifactSnapshot
from standing.lifecycle import RemediationStatus
from standing.memory import create_memory_store
from standing.model_review import (
    DecisionProposal,
    ExtractionProposal,
    confirm_extraction,
)
from standing.reviewer import ReviewerToolError, ReviewerTools


class ReviewerToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = create_memory_store(
            path=Path(self.directory.name) / "standing.db",
            tenant_id="reviewer-tests",
        )
        self.tools = ReviewerTools(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_review_reads_memory_and_blocks_only_when_evaluator_blocks(self) -> None:
        self.store.save_decision(
            "acme-events",
            {
                "title": "Use Acme for event persistence",
                "governed_paths": ["src/events/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )
        self.store.save_condition_reference(
            "vendor.acme.retention_days",
            {"accepted_value": 90, "accepted_source_url": "https://vendor.example/retention"},
            metadata={"observation_uid": "0xexpired"},
        )

        hits = self.tools.search_decisions(["src/events/archive.py"])
        reviews = self.tools.review_paths(["src/events/archive.py"])

        self.assertEqual([(hit.decision_id, hit.title) for hit in hits], [("acme-events", "Use Acme for event persistence")])
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].evaluation.state.value, "EXPIRED")
        self.assertTrue(reviews[0].blocks)
        condition = self.tools.read_condition("vendor.acme.retention_days")
        self.assertEqual(condition.body["accepted_value"], 90)

    def test_artifact_proposal_is_persisted_and_only_human_confirmation_creates_decision(self) -> None:
        artifact_path = Path(self.directory.name) / "ADR-0042.md"
        artifact_text = "Use Acme for archive persistence because retention is at least 365 days."
        artifact_path.write_text(artifact_text, encoding="utf-8")
        snapshot = ArtifactSnapshot.read(artifact_path, root=self.directory.name, captured_at=100)
        self.tools.ingest_artifact(snapshot)

        proposal = DecisionProposal(
            decision_id="ACME-001",
            title="Use Acme for archive persistence",
            description="Keep archive persistence on Acme.",
            governed_paths=("src/archive.py",),
            conditions=(
                {
                    "condition_key": "vendor.acme.retention_days",
                    "predicate": "retention_days >= 365",
                    "required": True,
                    "provenance": "INFERRED",
                    "unit": "days",
                },
            ),
            artifact_path=snapshot.path,
            artifact_type=snapshot.artifact_type,
            artifact_sha256=hashlib.sha256(artifact_text.encode("utf-8")).hexdigest(),
            source_sentence=artifact_text,
            rationale="The ADR states the choice and requirement.",
            model_id="gpt-5.4-mini",
        )
        stored = self.tools.record_decision_proposal(proposal)

        self.assertEqual(self.store.list_decision_proposals()[0]["name"], proposal.proposal_id)
        self.assertEqual(self.store.list_decision_proposals()[0]["body"]["status"], "PENDING")
        with self.assertRaises(ReviewerToolError):
            self.tools.confirm_decision_proposal(
                proposal.proposal_id,
                confirmed_by="model",
                confirmation_note="not allowed",
                confirmed_at=200,
            )
        confirmed = self.tools.confirm_decision_proposal(
            proposal.proposal_id,
            confirmed_by="alice",
            confirmation_note="I reviewed the ADR and confirm this blocking assumption.",
            confirmed_at=200,
        )

        self.assertEqual(confirmed.decision_id, "ACME-001")
        self.assertEqual(confirmed.body["approver"], "alice")
        self.assertEqual(confirmed.body["conditions"][0]["provenance"], "CONFIRMED")
        self.assertEqual(self.store.read_decision_proposal(proposal.proposal_id)["body"]["status"], "CONFIRMED")
        self.assertEqual(self.tools.current_decision("src/archive.py").decision_id, "ACME-001")
        events = self.store.read_standing_changes()
        self.assertTrue(any(event["extra"]["event_type"] == "decision_proposal_confirmed" for event in events))

    def test_confirmed_extraction_is_persisted_without_bypassing_acceptance(self) -> None:
        proposal = ExtractionProposal(
            condition_key="vendor.acme.retention_days",
            value=365,
            source_url="https://vendor.example/retention",
            effective_from=100,
            rationale="The source states the retention value.",
            model_id="gpt-5.4-mini",
        )
        confirmed = confirm_extraction(
            proposal,
            source_snapshot=b"Retention: 365 days.",
            confirmed_by="alice",
            confirmed_at=200,
            review_note="I checked the exact source snapshot.",
        )

        stored = self.tools.record_confirmed_extraction(
            confirmed,
            value_type="number",
            unit="days",
            recorded_at=300,
        )

        body = stored["body"]
        self.assertEqual(body["value"], 365)
        self.assertEqual(body["observed_at"], 200)
        self.assertEqual(body["recorded_at"], 300)
        self.assertEqual(body["extraction_method"], "MANUAL_VERIFIED")
        self.assertEqual(body["evidence_hash"], confirmed.source_sha256)
        self.assertIsNone(body.get("accepted"))
        events = self.store.read_standing_changes()
        self.assertTrue(
            any(event["extra"]["event_type"] == "extraction_confirmation_recorded" for event in events)
        )

    def test_proposal_rejection_is_human_only_and_does_not_create_decision(self) -> None:
        proposal = DecisionProposal(
            decision_id="REJECTED-001",
            title="Unadopted choice",
            description="This proposal is not ready.",
            governed_paths=("src/unadopted.py",),
            conditions=(
                {
                    "condition_key": "vendor.retention_days",
                    "predicate": "retention_days >= 365",
                    "required": True,
                    "provenance": "INFERRED",
                    "unit": "days",
                },
            ),
            artifact_path="docs/ADR-unadopted.md",
            artifact_type="ADR",
            artifact_sha256="b" * 64,
            source_sentence="This proposal is not ready.",
            rationale="Needs review.",
            model_id="gpt-5.4-mini",
        )
        self.tools.record_decision_proposal(proposal)

        rejected = self.tools.reject_decision_proposal(
            proposal.proposal_id,
            rejected_by="alice",
            reason="The source does not establish the assumption.",
            rejected_at=300,
        )

        self.assertEqual(rejected["body"]["status"], "REJECTED")
        with self.assertRaises(NotFoundError):
            self.store.read_decision("REJECTED-001")

    def test_standing_result_is_written_to_state_and_journal(self) -> None:
        self._save_decision_and_value(365)
        evaluation = self.tools.evaluate_standing("acme-events")

        event_id = self.tools.write_standing_change(
            "acme-events",
            evaluation,
            action="allow",
            explanation="The required retention remains at least 365 days.",
        )

        self.assertIsInstance(event_id, str)
        state = self.store.read_standing("acme-events")
        self.assertIsNotNone(state)
        self.assertEqual(state["state"], "STANDS")
        self.assertEqual(state["fingerprint"], evaluation.fingerprint)
        boot = self.tools.read_boot_state()
        self.assertEqual(len(boot.changes), 1)

    def test_reviewer_cannot_block_a_standing_result(self) -> None:
        self._save_decision_and_value(365)
        evaluation = self.tools.evaluate_standing("acme-events")

        with self.assertRaises(ReviewerToolError):
            self.tools.write_standing_change(
                "acme-events",
                evaluation,
                action="block",
                explanation="This text must not override the evaluator.",
            )
        self.assertIsNone(self.store.read_standing("acme-events"))
        self.assertEqual(self.tools.read_boot_state().changes, ())

    def test_missing_condition_is_unknown_and_can_be_blocked(self) -> None:
        self.store.save_decision(
            "acme-events",
            {
                "title": "Use Acme for event persistence",
                "governed_paths": ["src/events/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )

        review = self.tools.review_paths(["src/events/archive.py"])[0]

        self.assertEqual(review.evaluation.state.value, "UNKNOWN")
        self.assertTrue(review.blocks)

    def test_due_scheduled_recheck_makes_condition_unknown_until_revalidated(self) -> None:
        self._save_decision_and_value(365)
        self.store.save_condition_reference(
            "vendor.acme.retention_days",
            {
                "accepted_value": 365,
                "last_verified_at": 1,
                "recheck_interval_seconds": 1,
                "next_check_at": 1,
            },
            metadata={"observation_uid": "0x365"},
        )

        evaluation = self.tools.evaluate_standing("acme-events")

        self.assertEqual(evaluation.state.value, "UNKNOWN")
        self.assertTrue(evaluation.conditions[0].blocks)
        self.assertEqual(
            self.tools.current_condition_reference("vendor.acme.retention_days")["freshness_reason"],
            "scheduled recheck is due",
        )

    def test_revision_history_and_time_travel_are_persisted(self) -> None:
        first = {
            "decision_id": "versioned",
            "revision_id": "r1",
            "effective_from": 100,
            "body": {
                "title": "Use the first path",
                "governed_paths": ["src/versioned.py"],
                "conditions": [self._spec("vendor.retention")],
            },
        }
        second = {
            "decision_id": "versioned",
            "revision_id": "r2",
            "effective_from": 200,
            "supersedes_revision_id": "r1",
            "body": {
                "title": "Use the replacement path",
                "governed_paths": ["src/versioned.py"],
                "conditions": [self._spec("vendor.retention")],
            },
        }

        self.tools.record_decision_revision(first, actor_id="alice", reason="Initial decision.")
        self.tools.record_decision_revision(second, actor_id="alice", reason="The decision was replaced.")
        self.store.record_standing_change(
            evaluated={"decision_id": "versioned", "revision_id": "r1", "state": "EXPIRED"},
            acted={"action": "block", "explanation": "The first rule no longer holds."},
            forward={"revision_id": "r1"},
            extra={},
            ts="1970-01-01T00:02:00Z",
        )
        self.store.record_standing_change(
            evaluated={"decision_id": "versioned", "revision_id": "r2", "state": "STANDS"},
            acted={"action": "allow", "explanation": "The replacement rule holds."},
            forward={"revision_id": "r2"},
            extra={},
            ts="1970-01-01T00:03:20Z",
        )

        historic = self.tools.read_decision_at("versioned", as_of=199)
        current = self.tools.read_decision_at("versioned", as_of=200)

        self.assertEqual(historic.revision.revision_id if historic.revision else None, "r1")
        self.assertEqual(historic.standing.state if historic.standing else None, "EXPIRED")
        self.assertEqual(current.revision.revision_id if current.revision else None, "r2")
        self.assertEqual(current.standing.action if current.standing else None, "allow")

    def test_decision_path_queries_distinguish_valid_and_known_time(self) -> None:
        self.store.save_decision(
            "ACME-001",
            {
                "title": "Use Acme archive storage",
                "recorded_at": "2026-01-02",
                "effective_from": "2026-01-01",
                "superseded_at": "2026-09-07",
                "status": "SUPERSEDED",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )
        self.store.save_decision(
            "STORAGE-002",
            {
                "title": "Use Contoso archive storage",
                "recorded_at": "2026-09-09",
                "effective_from": "2026-09-07",
                "status": "CURRENT",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.contoso.retention_days")],
            },
        )

        current = self.tools.current_decision("src/archive.py")
        historic = self.tools.decision_as_of("src/archive.py", "2026-03-03")
        known = self.tools.decision_known_as_of("src/archive.py", "2026-03-03")

        self.assertEqual(current.decision_id if current else None, "STORAGE-002")
        self.assertEqual(historic.decision_id if historic else None, "ACME-001")
        self.assertEqual(known.decision_id if known else None, "ACME-001")

    def test_decision_known_as_of_does_not_apply_late_supersession_early(self) -> None:
        self.store.save_decision(
            "ACME-001",
            {
                "title": "Use Acme archive storage",
                "recorded_at": "2026-01-02",
                "effective_from": "2026-01-01",
                "status": "CURRENT",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )

        self.tools.record_replacement_decision(
            "ACME-001",
            "STORAGE-002",
            {
                "title": "Use Contoso archive storage",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.contoso.retention_days")],
            },
            actor_id="alice",
            reason="The Acme assumption expired.",
            effective_from="2026-09-07",
            recorded_at="2026-09-09",
        )

        before_discovery = self.tools.decision_known_as_of("src/archive.py", "2026-09-08")
        after_discovery = self.tools.decision_known_as_of("src/archive.py", "2026-09-10")

        self.assertEqual(before_discovery.decision_id if before_discovery else None, "ACME-001")
        self.assertEqual(after_discovery.decision_id if after_discovery else None, "STORAGE-002")

    def test_current_decision_ignores_future_effective_or_recorded_decisions(self) -> None:
        self.store.save_decision(
            "FUTURE-001",
            {
                "title": "Future archive choice",
                "recorded_at": "2099-01-01",
                "effective_from": "2099-01-02",
                "status": "CURRENT",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.future.archive")],
            },
        )

        self.assertIsNone(self.tools.current_decision("src/archive.py"))

    def test_replacement_decision_supersedes_old_record_without_deleting_it(self) -> None:
        self.store.save_decision(
            "ACME-001",
            {
                "title": "Use Acme archive storage",
                "recorded_at": "2026-01-02",
                "effective_from": "2026-01-01",
                "status": "CURRENT",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )

        replacement = self.tools.record_replacement_decision(
            "ACME-001",
            "STORAGE-002",
            {
                "title": "Use Contoso archive storage",
                "governed_paths": ["src/archive.py"],
                "conditions": [self._spec("vendor.contoso.retention_days")],
            },
            actor_id="alice",
            reason="Acme retention no longer meets the approved requirement.",
            effective_from="2026-09-07",
            recorded_at="2026-09-09",
        )

        old = self.store.read_decision("ACME-001")["body"]
        current = self.tools.current_decision("src/archive.py")
        historic = self.tools.decision_as_of("src/archive.py", "2026-03-03")

        self.assertEqual(replacement.decision_id, "STORAGE-002")
        self.assertEqual(old["status"], "SUPERSEDED")
        self.assertEqual(old["superseded_by"], "STORAGE-002")
        self.assertEqual(current.decision_id if current else None, "STORAGE-002")
        self.assertEqual(historic.decision_id if historic else None, "ACME-001")

    def test_full_text_false_match_does_not_become_a_governed_path_match(self) -> None:
        self.store.save_decision(
            "unrelated",
            {
                "title": "Mentions src/archive.py in discussion only",
                "governed_paths": ["docs/architecture.md"],
                "conditions": [self._spec("vendor.retention")],
            },
        )

        self.assertEqual(self.tools.search_decisions(["src/archive.py"]), ())

    def test_remediation_and_waiver_are_durable_and_waiver_does_not_change_state(self) -> None:
        self.store.save_decision(
            "waived-decision",
            {
                "title": "Use Acme for event persistence",
                "governed_paths": ["src/events/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )
        evaluation = self.tools.evaluate_standing("waived-decision")
        remediation = self.tools.open_remediation(
            "rem-1",
            "waived-decision",
            "r1",
            opened_at=100,
            summary="Obtain a fresh retention confirmation.",
            actor_id="alice",
        )
        transition = self.tools.transition_remediation(
            remediation.remediation_id,
            RemediationStatus.IN_PROGRESS,
            occurred_at=110,
            actor_id="reviewer",
            reason="The verification request is running.",
        )
        self.tools.issue_waiver(
            "waiver-1",
            "waived-decision",
            condition_key="vendor.acme.retention_days",
            reason="The incident commander accepted a temporary exception.",
            issued_by="alice",
            issuer_role="human",
            issued_at=100,
            expires_at=200,
        )

        event_id = self.tools.write_standing_change(
            "waived-decision",
            evaluation,
            action="allow",
            explanation="Proceed temporarily under the recorded human waiver.",
            waiver_id="waiver-1",
            now_unix=150,
        )

        self.assertIsInstance(event_id, str)
        self.assertEqual(transition.remediation.status, RemediationStatus.IN_PROGRESS)
        self.assertEqual(self.store.read_standing("waived-decision")["state"], "UNKNOWN")
        self.assertEqual(self.store.read_standing("waived-decision")["waiver"]["permits_action"], True)
        self.assertEqual(self.store.read_remediation("rem-1")["body"]["status"], "IN_PROGRESS")
        with self.assertRaises(ReviewerToolError):
            self.tools.write_standing_change(
                "waived-decision",
                evaluation,
                action="allow",
                explanation="The expired waiver must not continue to allow.",
                waiver_id="waiver-1",
                now_unix=200,
            )

    def test_reviewer_rejects_model_waiver_issuance(self) -> None:
        with self.assertRaises(ReviewerToolError):
            self.tools.issue_waiver(
                "waiver-model",
                "missing-decision",
                condition_key=None,
                reason="The model requests an exception.",
                issued_by="model",
                issuer_role="model",
                issued_at=100,
                expires_at=200,
            )

    def test_reviewer_persists_and_journals_evidence_bound_manual_approval(self) -> None:
        observations = [{"observation_uid": "one", "value": 365}]
        approval = issue_manual_approval(
            "approval-1",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=100,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the source-linked evidence.",
        )

        recorded = self.tools.record_manual_approval(approval)

        self.assertEqual(recorded.approval_id, "approval-1")
        self.assertEqual(self.store.read_manual_approval("approval-1")["body"]["approved_by"], "alice")
        self.assertEqual(self.store.list_manual_approvals("vendor.acme.retention_days")[0]["name"], "approval-1")
        self.assertEqual(
            self.store.read_standing_changes()[0]["extra"]["event_type"],
            "manual_approval_recorded",
        )

    def _save_decision_and_value(self, value: int) -> None:
        self.store.save_decision(
            "acme-events",
            {
                "title": "Use Acme for event persistence",
                "governed_paths": ["src/events/archive.py"],
                "conditions": [self._spec("vendor.acme.retention_days")],
            },
        )
        self.store.save_condition_reference(
            "vendor.acme.retention_days",
            {"accepted_value": value},
            metadata={"observation_uid": f"0x{value}"},
        )

    @staticmethod
    def _spec(key: str) -> dict[str, object]:
        return {
            "condition_key": key,
            "predicate": "retention_days >= 365",
            "provenance": "CONFIRMED",
            "required": True,
        }


if __name__ == "__main__":
    unittest.main()
