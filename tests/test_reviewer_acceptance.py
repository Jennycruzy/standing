import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.acp import VerifierObservation
from standing.acceptance import load_acceptance_policy
from standing.memory import create_memory_store
from standing.provenance import ObservationProvenance
from standing.reviewer import ReviewerTools


class ReviewerAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = create_memory_store(
            path=Path(self.directory.name) / "standing.db",
            tenant_id="acceptance-reviewer-tests",
        )
        self.tools = ReviewerTools(self.store)
        self.policy = load_acceptance_policy(Path(__file__).parents[1] / "config" / "policy.json")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_reviewer_reads_observer_history_for_acceptance_and_selection(self) -> None:
        self.store.save_observer(
            "0x111",
            {"readings_given": 3, "readings_confirmed": 3, "readings_contradicted": 0},
        )
        self.store.save_observer(
            "0x222",
            {"readings_given": 4, "readings_confirmed": 4, "readings_contradicted": 0},
        )
        observations = [
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 365,
                "source_type": "vendor_primary",
                "observation_uid": "0xprimary",
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 365,
                "source_type": "verifier",
                "observer_address": "0x111",
                "observation_uid": "0xone",
                "provenance": {
                    "operator_id": "operator:one",
                    "source_id": "source:one",
                    "extractor_id": "extractor:one",
                },
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 365,
                "source_type": "verifier",
                "observer_address": "0x222",
                "observation_uid": "0xtwo",
                "provenance": {
                    "operator_id": "operator:two",
                    "source_id": "source:two",
                    "extractor_id": "extractor:two",
                },
            },
        ]
        approval = issue_manual_approval(
            "approval-1",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=1_700_000_200,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the source-linked readings.",
        )

        result = self.tools.check_acceptance(
            "vendor.acme.retention_days",
            observations,
            manual_approval=True,
            manual_approval_record=approval.as_dict(),
            policy=self.policy,
        )
        selected = self.tools.select_observer(["0x111", "0x222"], self.policy)

        self.assertTrue(result.accepted)
        self.assertEqual(selected.address, "0x222")

    def test_reviewer_writes_the_observer_outcome_back_to_memory(self) -> None:
        self.store.save_observer(
            "0x111",
            {"readings_given": 3, "readings_confirmed": 3, "readings_contradicted": 0},
        )

        updated = self.tools.record_observer_outcome("0x111", confirmed=False)

        self.assertEqual(updated.readings_given, 4)
        self.assertEqual(updated.readings_confirmed, 3)
        self.assertEqual(updated.readings_contradicted, 1)
        stored = self.store.read_observer("0x111")
        self.assertEqual(stored["body"]["readings_contradicted"], 1)

    def test_reviewer_persists_and_reads_checked_observations(self) -> None:
        observation = {
            "condition_key": "vendor.acme.retention_days",
            "value": 365,
            "source_type": "verifier",
            "observer_address": "0x111",
            "observation_uid": "0xone",
        }

        stored = self.tools.record_observation(observation)

        self.assertEqual(stored["body"], observation)
        self.assertEqual(self.tools.read_observations("vendor.acme.retention_days"), (observation,))

    def test_verifier_delivery_keeps_seller_observation_and_local_receipt_times(self) -> None:
        observation = VerifierObservation(
            condition_key="vendor.acme.retention_days",
            value=90,
            source_type="verifier",
            source_url="https://vendor.example/retention",
            observation_uid="0xverifier",
            observer_address="0x111",
            effective_from=1_000,
            note="CONTROLLED DEMO DATA — extracted from source",
            disclosure="CONTROLLED DEMO DATA",
            job_id="job-1",
            observation_transaction=None,
            provenance=ObservationProvenance(
                operator_id="operator:one",
                source_id="source:one",
                extractor_id="extractor:one",
            ),
            value_type="number",
            unit="days",
            observed_at=1_000,
            recorded_at=1_000,
            extraction_method="JSON_PATH",
            extraction_version="retention-json-v1",
            evidence_hash="a" * 64,
            source_snapshot_hash="b" * 64,
        )

        stored = self.tools.record_verifier_observation(observation, recorded_at=2_000)
        body = stored["body"]

        self.assertEqual(body["observed_at"], 1_000)
        self.assertEqual(body["recorded_at"], 2_000)
        self.assertEqual(body["knowledge_recorded_by"], "standing:reviewer")
        observer = self.store.read_observer("0x111")["body"]
        self.assertEqual(observer["wallet_address"], "0x111")
        self.assertEqual(observer["operator_id"], "operator:one")
        self.assertEqual(observer["source_domains"], ["vendor.example"])
        self.assertEqual(observer["extraction_methods"], ["JSON_PATH"])
        self.assertEqual(observer["extraction_versions"], ["retention-json-v1"])

    def test_new_verifier_period_is_linked_to_the_previous_temporal_head(self) -> None:
        self.tools.record_temporal_observation(
            self._temporal_observation("old", 365, "1970-01-01")
        )
        observation = VerifierObservation(
            condition_key="vendor.acme.retention_days",
            value=90,
            source_type="verifier",
            source_url="https://vendor.example/retention",
            observation_uid="0x" + "ab" * 32,
            observer_address="0x111",
            effective_from=2_000,
            note="CONTROLLED DEMO DATA — extracted from source",
            disclosure="CONTROLLED DEMO DATA",
            job_id="job-2",
            observation_transaction=None,
            provenance=ObservationProvenance(
                operator_id="operator:one",
                source_id="source:one",
                extractor_id="extractor:one",
            ),
            value_type="number",
            unit="days",
            observed_at=2_000,
            recorded_at=2_000,
            extraction_method="JSON_PATH",
            extraction_version="retention-json-v1",
            evidence_hash="c" * 64,
            source_snapshot_hash="d" * 64,
        )

        stored = self.tools.record_verifier_observation(observation, recorded_at=3_000)

        self.assertEqual(stored["body"]["ref_uid"], "old")

    def test_acceptance_promotion_updates_condition_and_dependents(self) -> None:
        self.store.save_observer(
            "0x111",
            {
                "readings_given": 3,
                "readings_confirmed": 3,
                "readings_contradicted": 0,
            },
        )
        self.store.save_observer(
            "0x222",
            {
                "readings_given": 3,
                "readings_confirmed": 3,
                "readings_contradicted": 0,
            },
        )
        self.store.save_decision(
            "ACME-001",
            {
                "title": "Use Acme for archive persistence",
                "governed_paths": ["src/archive.py"],
                "conditions": [
                    {
                        "condition_key": "vendor.acme.retention_days",
                        "predicate": "retention_days >= 365",
                        "provenance": "CONFIRMED",
                        "required": True,
                    }
                ],
            },
        )
        observations = [
            self._temporal_observation("vendor-old", 365, "2026-01-01"),
            self._temporal_observation("observer-one", 365, "2026-01-01", observer="0x111"),
            self._temporal_observation("observer-two", 365, "2026-01-01", observer="0x222"),
            self._temporal_observation(
                "vendor-current",
                90,
                "2026-09-07",
                ref_uid="vendor-old",
            ),
        ]
        policy = self.policy.__class__(
            vendor_primary_source_type="vendor_primary",
            independent_observers=2,
            min_observer_history=3,
            max_observer_contradictions=0,
            manual_approval_required=True,
            require_independence_provenance=True,
        )
        approval = issue_manual_approval(
            "approval-promotion",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=1_700_000_200,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the superseding vendor reading.",
        )
        result = self.tools.check_acceptance(
            "vendor.acme.retention_days",
            observations,
            manual_approval=True,
            manual_approval_record=approval.as_dict(),
            policy=policy,
            now_unix=int(datetime(2026, 9, 9, tzinfo=timezone.utc).timestamp()),
        )

        promotion = self.tools.promote_acceptance(
            "vendor.acme.retention_days",
            result,
            observations,
            accepted_at="2026-09-09",
            recheck_interval_seconds=31536000,
        )

        self.assertEqual(promotion.affected_decision_ids, ("ACME-001",))
        self.assertEqual(promotion.condition_reference["accepted_value"], 90)
        self.assertEqual(promotion.condition_reference["observation_uids"], ["vendor-current"])
        reference = self.store.read_condition_reference("vendor.acme.retention_days")
        self.assertIsNotNone(reference)
        self.assertEqual(reference["body"]["accepted_value"], 90)
        self.assertEqual(reference["body"]["recheck_interval_seconds"], 31536000)
        self.assertEqual(reference["body"]["next_check_at"], 1820448000)
        persisted = {row["observation_uid"]: row for row in self.tools.read_observations("vendor.acme.retention_days")}
        self.assertTrue(all(row.get("accepted") is True for row in persisted.values()))
        standing = self.store.read_standing("ACME-001")
        self.assertIsNotNone(standing)
        self.assertEqual(standing["state"], "EXPIRED")
        self.assertEqual(standing["action"], "block")
        self.assertTrue(promotion.standing_change_event_ids)

    @staticmethod
    def _temporal_observation(
        uid: str,
        value: int,
        effective_from: str,
        *,
        observer: str | None = None,
        ref_uid: str | None = None,
    ) -> dict[str, object]:
        observation: dict[str, object] = {
            "condition_key": "vendor.acme.retention_days",
            "value": value,
            "value_type": "number",
            "unit": "days",
            "effective_from": effective_from,
            "observed_at": "2026-09-08",
            "recorded_at": "2026-09-09",
            "source_url": "https://vendor.example/retention",
            "source_type": "verifier" if observer else "vendor_primary",
            "attester": observer or "attester:acme",
            "operator_id": f"operator:{observer or 'acme'}",
            "extraction_method": "HTML_SELECTOR",
            "extraction_version": "retention-html-v1",
            "observation_uid": uid,
            "ref_uid": ref_uid,
            "evidence_hash": "a" * 64,
            "notes": "hand verified",
            "publisher_id": "publisher:acme",
        }
        if observer is not None:
            observation["observer_address"] = observer
            observation["provenance"] = {
                "operator_id": f"operator:{observer}",
                "source_id": f"source:{observer}",
                "extractor_id": f"extractor:{observer}",
            }
        return observation


if __name__ == "__main__":
    unittest.main()
