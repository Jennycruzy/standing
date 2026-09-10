import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from standing.approval import evidence_fingerprint, issue_manual_approval
from standing.acceptance import (
    AcceptancePolicy,
    AcceptanceStatus,
    ObserverHistory,
    ObserverSelectionError,
    apply_observer_outcome,
    check_acceptance,
    load_acceptance_policy,
    select_observer,
)


class AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_acceptance_policy(Path(__file__).parents[1] / "config" / "policy.json")

    def test_config_contains_the_runtime_policy(self) -> None:
        self.assertEqual(self.policy.vendor_primary_source_type, "vendor_primary")
        self.assertEqual(self.policy.independent_observers, 2)
        self.assertEqual(self.policy.min_observer_history, 3)
        self.assertEqual(self.policy.max_observer_contradictions, 0)
        self.assertTrue(self.policy.manual_approval_required)
        self.assertTrue(self.policy.require_independence_provenance)
        self.assertEqual(self.policy.max_observation_age_seconds, 86400)
        self.assertEqual(self.policy.recheck_interval_seconds, 86400)

    def test_two_clean_observers_and_vendor_source_are_accepted(self) -> None:
        observations = self._observations(365)
        approval = issue_manual_approval(
            "approval-1",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=1_700_000_200,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the three source-linked readings.",
        )
        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            manual_approval_record=approval.as_dict(),
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.ACCEPTED)
        self.assertTrue(result.accepted)
        self.assertEqual(result.accepted_value, 365)
        self.assertEqual(result.independent_observer_addresses, ("0x111", "0x222"))
        self.assertEqual(result.observation_uids, ("0xone", "0xprimary", "0xtwo"))
        self.assertTrue(result.manual_approval_valid)
        self.assertEqual(result.manual_approval_id, "approval-1")

    def test_manual_approval_must_match_the_exact_evidence_set(self) -> None:
        observations = self._observations(365)
        approval = issue_manual_approval(
            "approval-1",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=1_700_000_200,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the source-linked readings.",
        )
        changed = [*observations]
        changed[-1] = {**changed[-1], "value": 90}

        result = check_acceptance(
            "vendor.acme.retention_days",
            changed,
            self._records(),
            manual_approval=True,
            manual_approval_record=approval.as_dict(),
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(any("different evidence set" in reason for reason in result.reasons))

    def test_manual_approval_record_is_required_when_flag_is_true(self) -> None:
        result = check_acceptance(
            "vendor.acme.retention_days",
            self._observations(365),
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(any("persisted human approval" in reason for reason in result.reasons))

    def test_source_binding_requires_the_canonical_vendor_and_trusted_host(self) -> None:
        observations = self._observations(365)
        observations[0] = {
            **observations[0],
            "source_url": "https://vendor.example.evil/retention",
        }

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
            source_binding={
                "allowed_hosts": ["vendor.example"],
                "canonical_url": "https://vendor.example/retention",
                "publisher_id": "publisher:acme",
            },
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertFalse(result.vendor_primary_present)
        self.assertTrue(any("canonical trusted source" in reason for reason in result.reasons))

    def test_shared_operator_source_or_extractor_is_not_independent(self) -> None:
        observations = self._observations(365)
        observations[-1] = {
            **observations[-1],
            "provenance": {
                "operator_id": "operator:one",
                "source_id": "source:one",
                "extractor_id": "extractor:one",
            },
        }

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(any("share an operator identity" in reason for reason in result.reasons))
        self.assertTrue(any("share a source identity" in reason for reason in result.reasons))
        self.assertTrue(any("share an extractor identity" in reason for reason in result.reasons))

    def test_missing_independence_provenance_is_explicitly_contested(self) -> None:
        observations = self._observations(365)
        observations[1] = {key: value for key, value in observations[1].items() if key != "provenance"}

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(any("missing operator" in reason for reason in result.reasons))

    def test_stale_evidence_requires_revalidation(self) -> None:
        observations = self._observations(365)
        for observation in observations:
            observation["effective_from"] = 100

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
            now_unix=100 + self.policy.max_observation_age_seconds + 1,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(result.freshness_checked)
        self.assertEqual(len(result.stale_observation_uids), 3)
        self.assertTrue(any("stale" in reason for reason in result.reasons))

    def test_disagreement_is_contested_even_with_clean_histories(self) -> None:
        observations = self._observations(365)
        observations[-1] = {**observations[-1], "value": 90}

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertFalse(result.accepted)
        self.assertIn("disagree", " ".join(result.reasons))

    def test_temporal_change_is_accepted_as_current_without_being_contested(self) -> None:
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
        policy = AcceptancePolicy(
            vendor_primary_source_type="vendor_primary",
            independent_observers=2,
            min_observer_history=3,
            max_observer_contradictions=0,
            manual_approval_required=True,
            require_independence_provenance=True,
        )
        approval = issue_manual_approval(
            "approval-temporal",
            "vendor.acme.retention_days",
            approved_by="alice",
            approver_role="human",
            approved_at=1_700_000_200,
            evidence_digest=evidence_fingerprint("vendor.acme.retention_days", observations),
            reason="Reviewed the superseding vendor reading.",
        )

        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            manual_approval_record=approval.as_dict(),
            policy=policy,
            now_unix=int(datetime(2026, 9, 9, tzinfo=timezone.utc).timestamp()),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.accepted_value, 90)
        self.assertEqual(result.canonical_observation_uids, ("vendor-current",))
        self.assertFalse(result.temporal_conflict)
        self.assertNotIn("disagree", " ".join(result.reasons))

    def test_missing_history_and_manual_approval_contest_the_value(self) -> None:
        result = check_acceptance(
            "vendor.acme.retention_days",
            self._observations(365)[:2],
            {"0x111": self._records()["0x111"]},
            manual_approval=False,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.CONTESTED)
        self.assertTrue(any("independent observer" in reason for reason in result.reasons))
        self.assertTrue(any("approval" in reason for reason in result.reasons))

    def test_selection_prefers_clean_history_then_success_count(self) -> None:
        relaxed = AcceptancePolicy(
            vendor_primary_source_type="vendor_primary",
            independent_observers=1,
            min_observer_history=3,
            max_observer_contradictions=1,
            manual_approval_required=True,
        )
        histories = [
            ObserverHistory("0xunclean", 4, 3, 1),
            ObserverHistory("0xclean", 5, 5, 0),
            ObserverHistory("0xcleaner", 3, 3, 0),
        ]

        selected = select_observer(histories, relaxed)

        self.assertEqual(selected.address, "0xclean")

    def test_selection_fails_without_an_eligible_history(self) -> None:
        with self.assertRaises(ObserverSelectionError):
            select_observer([ObserverHistory("0xnew", 1, 1, 0)], self.policy)

    def test_observer_outcome_updates_the_counts(self) -> None:
        history = ObserverHistory("0x111", 3, 3, 0)

        contradicted = apply_observer_outcome(history, confirmed=False)
        confirmed = apply_observer_outcome(history, confirmed=True)

        self.assertEqual(contradicted.as_counts(), {
            "readings_given": 4,
            "readings_confirmed": 3,
            "readings_contradicted": 1,
        })
        self.assertEqual(confirmed.as_counts(), {
            "readings_given": 4,
            "readings_confirmed": 4,
            "readings_contradicted": 0,
        })

    def test_observer_identity_metadata_round_trips_and_survives_outcomes(self) -> None:
        history = ObserverHistory.from_mapping(
            "0x111",
            {
                "readings_given": 3,
                "readings_confirmed": 3,
                "readings_contradicted": 0,
                "wallet_address": "0x111",
                "operator_id": "operator:one",
                "operator_type": "individual",
                "source_domains": ["docs.example", "status.example", "docs.example"],
                "extraction_methods": ["HTML_SELECTOR"],
                "extraction_versions": ["retention-html-v1"],
            },
        )

        self.assertEqual(history.as_dict(), {
            "readings_given": 3,
            "readings_confirmed": 3,
            "readings_contradicted": 0,
            "wallet_address": "0x111",
            "operator_id": "operator:one",
            "operator_type": "individual",
            "source_domains": ["docs.example", "status.example"],
            "extraction_methods": ["HTML_SELECTOR"],
            "extraction_versions": ["retention-html-v1"],
        })
        updated = apply_observer_outcome(history, confirmed=True)
        self.assertEqual(updated.operator_id, "operator:one")
        self.assertEqual(updated.source_domains, ("docs.example", "status.example"))

    def test_observer_wallet_identity_cannot_disagree_with_entity_key(self) -> None:
        with self.assertRaises(ValueError):
            ObserverHistory.from_mapping("0x111", {"wallet_address": "0x222"})

    def test_result_is_json_serializable(self) -> None:
        result = check_acceptance(
            "vendor.acme.retention_days",
            self._observations(365),
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        json.dumps(result.as_dict(), sort_keys=True)

    @staticmethod
    def _records() -> dict[str, dict[str, int]]:
        return {
            "0x111": {"readings_given": 3, "readings_confirmed": 3, "readings_contradicted": 0},
            "0x222": {"readings_given": 4, "readings_confirmed": 4, "readings_contradicted": 0},
        }

    @staticmethod
    def _observations(value: int) -> list[dict[str, object]]:
        return [
            {
                "condition_key": "vendor.acme.retention_days",
                "value": value,
                "source_type": "vendor_primary",
                "observation_uid": "0xprimary",
                "source_url": "https://vendor.example/retention",
                "publisher_id": "publisher:acme",
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": value,
                "source_type": "verifier",
                "observer_address": "0x111",
                "observation_uid": "0xone",
                "source_url": "https://vendor.example/retention",
                "provenance": {
                    "operator_id": "operator:one",
                    "source_id": "source:one",
                    "extractor_id": "extractor:one",
                },
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": value,
                "source_type": "verifier",
                "observer_address": "0x222",
                "observation_uid": "0xtwo",
                "source_url": "https://vendor.example/retention",
                "provenance": {
                    "operator_id": "operator:two",
                    "source_id": "source:two",
                    "extractor_id": "extractor:two",
                },
            },
        ]

    @staticmethod
    def _temporal_observation(
        uid: str,
        value: int,
        effective_from: str,
        *,
        observer: str | None = None,
        ref_uid: str | None = None,
    ) -> dict[str, object]:
        source_type = "verifier" if observer is not None else "vendor_primary"
        observation: dict[str, object] = {
            "condition_key": "vendor.acme.retention_days",
            "value": value,
            "value_type": "number",
            "unit": "days",
            "effective_from": effective_from,
            "observed_at": "2026-09-08",
            "recorded_at": "2026-09-09",
            "source_url": "https://vendor.example/retention",
            "source_type": source_type,
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
