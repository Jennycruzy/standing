import tempfile
import unittest
from pathlib import Path

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.lifecycle import RemediationStatus
from standing.memory import create_memory_store
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
