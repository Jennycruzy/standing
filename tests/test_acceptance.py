import json
import unittest
from pathlib import Path

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

    def test_two_clean_observers_and_vendor_source_are_accepted(self) -> None:
        observations = self._observations(365)
        result = check_acceptance(
            "vendor.acme.retention_days",
            observations,
            self._records(),
            manual_approval=True,
            policy=self.policy,
        )

        self.assertEqual(result.status, AcceptanceStatus.ACCEPTED)
        self.assertTrue(result.accepted)
        self.assertEqual(result.accepted_value, 365)
        self.assertEqual(result.independent_observer_addresses, ("0x111", "0x222"))
        self.assertEqual(result.observation_uids, ("0xone", "0xprimary", "0xtwo"))

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
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": value,
                "source_type": "verifier",
                "observer_address": "0x111",
                "observation_uid": "0xone",
            },
            {
                "condition_key": "vendor.acme.retention_days",
                "value": value,
                "source_type": "verifier",
                "observer_address": "0x222",
                "observation_uid": "0xtwo",
            },
        ]


if __name__ == "__main__":
    unittest.main()
