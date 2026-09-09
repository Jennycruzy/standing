import unittest

from standing.evaluation import EvaluationDataset
from standing.release import ReleaseEvidence, check_release_gates


class ReleaseGateTests(unittest.TestCase):
    def test_release_requires_real_evidence_and_distinct_operators(self) -> None:
        result = check_release_gates(
            ReleaseEvidence(
                controlled_demo_disclosed=True,
                real_vendor_expiry_present=True,
                real_evaluation_case_count=3,
                independent_operator_ids=("operator:one", "operator:two"),
            )
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.reasons, ())

    def test_current_controlled_demo_is_not_release_ready(self) -> None:
        result = check_release_gates(
            ReleaseEvidence(
                controlled_demo_disclosed=True,
                real_vendor_expiry_present=False,
                real_evaluation_case_count=0,
                independent_operator_ids=("operator:standing",),
            )
        )

        self.assertFalse(result.ready)
        self.assertEqual(len(result.reasons), 3)
        self.assertTrue(any("vendor-expiry" in reason for reason in result.reasons))

    def test_duplicate_operator_ids_do_not_count_twice(self) -> None:
        result = check_release_gates(
            ReleaseEvidence(
                controlled_demo_disclosed=True,
                real_vendor_expiry_present=True,
                real_evaluation_case_count=3,
                independent_operator_ids=("operator:standing", "operator:standing"),
            )
        )

        self.assertFalse(result.ready)
        self.assertTrue(any("independent operator" in reason for reason in result.reasons))

    def test_release_evidence_can_take_its_case_count_from_validated_dataset(self) -> None:
        dataset = EvaluationDataset.from_mapping({"dataset_id": "empty-v1", "cases": []})

        evidence = ReleaseEvidence.from_dataset(
            dataset,
            controlled_demo_disclosed=True,
            real_vendor_expiry_present=False,
            independent_operator_ids=("operator:standing",),
        )

        self.assertEqual(evidence.real_evaluation_case_count, 0)

    def test_release_evidence_derives_vendor_expiry_from_dataset(self) -> None:
        dataset = EvaluationDataset.from_mapping(
            {
                "dataset_id": "real-v1",
                "cases": [
                    {
                        "case_id": "expired",
                        "repository": "owner/repository",
                        "decision_url": "https://github.com/owner/repository/blob/main/decision.md",
                        "decision_ref": "main:decision.md",
                        "ground_truth_url": "https://vendor.example.com/history",
                        "ground_truth_source_type": "vendor_history",
                        "ground_truth_effective_at": 1_700_000_000,
                        "captured_at": 1_700_000_100,
                        "source_sha256": "a" * 64,
                        "expected_state": "EXPIRED",
                        "synthetic": False,
                    }
                ],
            }
        )

        evidence = ReleaseEvidence.from_dataset(
            dataset,
            controlled_demo_disclosed=True,
            independent_operator_ids=("operator:one",),
        )

        self.assertTrue(evidence.real_vendor_expiry_present)
        self.assertEqual(evidence.real_evaluation_case_count, 1)


if __name__ == "__main__":
    unittest.main()
