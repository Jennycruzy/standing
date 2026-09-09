import unittest

from standing.lifecycle import (
    LifecycleError,
    Remediation,
    RemediationStatus,
    build_revision_timeline,
    check_waiver,
    decision_at,
    issue_waiver,
    project_standing_timeline,
    transition_remediation,
)


class LifecycleTests(unittest.TestCase):
    def test_revision_timeline_selects_the_revision_active_at_each_time(self) -> None:
        revisions = [
            self._revision("r1", 100),
            self._revision("r2", 200, supersedes="r1", threshold=365),
        ]

        before = build_revision_timeline("decision", revisions, as_of=199)
        after = build_revision_timeline("decision", revisions, as_of=200)

        self.assertEqual(before.active_revision.revision_id if before.active_revision else None, "r1")
        self.assertEqual(after.active_revision.revision_id if after.active_revision else None, "r2")
        self.assertEqual(after.active_revision.body["threshold"] if after.active_revision else None, 365)

    def test_revision_chain_rejects_missing_parent_and_forks(self) -> None:
        with self.assertRaises(LifecycleError):
            build_revision_timeline(
                "decision",
                [self._revision("r2", 200, supersedes="missing")],
            )

        with self.assertRaises(LifecycleError):
            build_revision_timeline(
                "decision",
                [
                    self._revision("r1", 100),
                    self._revision("r2", 200, supersedes="r1"),
                    self._revision("r3", 300, supersedes="r1"),
                ],
            )

    def test_remediation_has_a_constrained_auditable_lifecycle(self) -> None:
        remediation = Remediation.create(
            "rem-1",
            "decision",
            "r1",
            opened_at=100,
            summary="Revalidate the vendor retention promise.",
        )
        started = transition_remediation(
            remediation,
            RemediationStatus.IN_PROGRESS,
            occurred_at=110,
            actor_id="reviewer",
            reason="A fresh verification is underway.",
        )
        superseded = transition_remediation(
            started.remediation,
            RemediationStatus.SUPERSEDED,
            occurred_at=120,
            actor_id="human-owner",
            reason="The decision was replaced by a new revision.",
            superseded_by_revision_id="r2",
        )

        self.assertEqual(superseded.remediation.status, RemediationStatus.SUPERSEDED)
        self.assertEqual(superseded.remediation.superseded_by_revision_id, "r2")
        with self.assertRaises(LifecycleError):
            transition_remediation(
                superseded.remediation,
                RemediationStatus.OPEN,
                occurred_at=130,
                actor_id="reviewer",
                reason="Must not reopen a superseded record.",
            )

    def test_only_humans_can_issue_waivers_and_expiry_restores_gate(self) -> None:
        with self.assertRaises(LifecycleError):
            issue_waiver(
                "w-model",
                "decision",
                condition_key="vendor.retention",
                reason="The model wants to continue.",
                issued_by="model",
                issuer_role="model",
                issued_at=100,
                expires_at=200,
            )

        waiver = issue_waiver(
            "w-human",
            "decision",
            condition_key="vendor.retention",
            reason="The incident commander accepted the temporary risk.",
            issued_by="alice",
            issuer_role="human",
            issued_at=100,
            expires_at=200,
        )
        active = check_waiver(
            waiver,
            decision_id="decision",
            blocking_condition_keys=["vendor.retention"],
            now_unix=150,
        )
        expired = check_waiver(
            waiver,
            decision_id="decision",
            blocking_condition_keys=["vendor.retention"],
            now_unix=200,
        )

        self.assertTrue(active.permits_action)
        self.assertFalse(expired.permits_action)
        self.assertTrue(expired.automatically_restored)

    def test_decision_at_is_a_time_travel_view_over_revisions_and_journal(self) -> None:
        revisions = [
            self._revision("r1", 100),
            self._revision("r2", 200, supersedes="r1"),
        ]
        events = [
            self._event("e1", 100, "r1", "EXPIRED", "block"),
            self._event("e2", 200, "r2", "STANDS", "allow"),
        ]

        snapshot = decision_at("decision", revisions, events, as_of=199)
        current = decision_at("decision", revisions, events, as_of=200)

        self.assertEqual(snapshot.revision.revision_id if snapshot.revision else None, "r1")
        self.assertEqual(snapshot.standing.state if snapshot.standing else None, "EXPIRED")
        self.assertEqual(current.revision.revision_id if current.revision else None, "r2")
        self.assertEqual(current.standing.action if current.standing else None, "allow")
        self.assertEqual(len(current.standing_history), 2)

    def test_timeline_is_deterministic_and_filters_other_decisions(self) -> None:
        events = [
            self._event("e2", 200, "r1", "STANDS", "allow"),
            self._event("other", 1, "r1", "EXPIRED", "block", decision="other"),
            self._event("e1", 200, "r1", "EXPIRED", "block"),
        ]

        timeline = project_standing_timeline(events, "decision")

        self.assertEqual([event.event_id for event in timeline.events], ["e1", "e2"])
        self.assertEqual(timeline.current.event_id if timeline.current else None, "e2")

    @staticmethod
    def _revision(
        revision_id: str,
        effective_from: int,
        *,
        supersedes: str | None = None,
        threshold: int = 90,
    ) -> dict[str, object]:
        return {
            "decision_id": "decision",
            "revision_id": revision_id,
            "effective_from": effective_from,
            "supersedes_revision_id": supersedes,
            "body": {"decision_id": "decision", "threshold": threshold},
        }

    @staticmethod
    def _event(
        event_id: str,
        ts: int,
        revision_id: str,
        state: str,
        action: str,
        *,
        decision: str = "decision",
    ) -> dict[str, object]:
        return {
            "id": event_id,
            "ts": ts,
            "evaluated": {
                "decision_id": decision,
                "revision_id": revision_id,
                "state": state,
                "fingerprint": f"fingerprint-{event_id}",
            },
            "acted": {"action": action, "explanation": f"Explanation {event_id}"},
            "forward": {"revision_id": revision_id},
            "extra": {},
        }


if __name__ == "__main__":
    unittest.main()
