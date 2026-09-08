import tempfile
import unittest
from pathlib import Path

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
