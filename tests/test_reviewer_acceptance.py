import tempfile
import unittest
from pathlib import Path

from standing.acceptance import load_acceptance_policy
from standing.memory import create_memory_store
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

        result = self.tools.check_acceptance(
            "vendor.acme.retention_days",
            observations,
            manual_approval=True,
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


if __name__ == "__main__":
    unittest.main()
