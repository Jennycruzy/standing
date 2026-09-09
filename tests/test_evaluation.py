import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from standing.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationDatasetError,
    measure_predictions,
    sha256_bytes,
)
from standing.evaluator import StandingState


class EvaluationDatasetTests(unittest.TestCase):
    def test_source_linked_cases_separate_real_and_synthetic_counts(self) -> None:
        dataset = EvaluationDataset.from_mapping(
            {
                "dataset_id": "dataset-v1",
                "cases": [self._case("real", synthetic=False), self._case("synthetic", synthetic=True)],
            }
        )

        self.assertEqual(dataset.release_case_count(), 1)
        self.assertEqual([case.case_id for case in dataset.synthetic_cases], ["synthetic"])

    def test_real_vendor_expiry_ignores_synthetic_and_non_vendor_cases(self) -> None:
        real_expired = self._case("real-expired", expected="EXPIRED", synthetic=False)
        synthetic_expired = self._case("synthetic-expired", expected="EXPIRED", synthetic=True)
        repository_expired = self._case("repository-expired", expected="EXPIRED", synthetic=False)
        repository_expired["ground_truth_source_type"] = "repository_history"
        dataset = EvaluationDataset.from_mapping(
            {
                "dataset_id": "dataset-v1",
                "cases": [real_expired, synthetic_expired, repository_expired],
            }
        )

        self.assertTrue(dataset.has_real_vendor_expiry)
        self.assertEqual([case.case_id for case in dataset.real_vendor_expiry_cases], ["real-expired"])

    def test_missing_or_unpinned_source_fields_are_rejected(self) -> None:
        raw = self._case("case", synthetic=False)
        raw.pop("source_sha256")
        with self.assertRaises(EvaluationDatasetError):
            EvaluationCase.from_mapping(raw)

        raw = self._case("case", synthetic=False)
        raw["ground_truth_url"] = "https://example.com/vendor-history"
        with self.assertRaises(EvaluationDatasetError):
            EvaluationCase.from_mapping(raw)

    def test_real_cases_require_explicit_non_synthetic_flag(self) -> None:
        raw = self._case("case", synthetic=False)
        raw.pop("synthetic")
        with self.assertRaises(EvaluationDatasetError):
            EvaluationCase.from_mapping(raw)

    def test_measurement_reports_missing_cases_and_mismatches(self) -> None:
        dataset = EvaluationDataset.from_mapping(
            {
                "dataset_id": "dataset-v1",
                "cases": [
                    self._case("stands", expected="STANDS"),
                    self._case("expired", expected="EXPIRED"),
                    self._case("unknown", expected="UNKNOWN"),
                ],
            }
        )

        metrics = measure_predictions(
            dataset,
            {"stands": StandingState.STANDS, "expired": "STANDS"},
        )

        self.assertEqual(metrics.total_cases, 3)
        self.assertEqual(metrics.evaluated_cases, 2)
        self.assertEqual(metrics.correct_cases, 1)
        self.assertEqual(metrics.missing_case_ids, ("unknown",))
        self.assertEqual(metrics.mismatches[0].case_id, "expired")
        self.assertEqual(metrics.accuracy, 0.5)

    def test_measurement_rejects_predictions_for_unknown_cases(self) -> None:
        dataset = EvaluationDataset.from_mapping(
            {"dataset_id": "dataset-v1", "cases": [self._case("known")]}
        )
        with self.assertRaises(EvaluationDatasetError):
            measure_predictions(dataset, {"unknown": "STANDS"})

    def test_dataset_load_and_digest_helper_are_deterministic(self) -> None:
        payload = b"captured source"
        self.assertEqual(sha256_bytes(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(
                json.dumps({"dataset_id": "dataset-v1", "cases": [self._case("one")]}),
                encoding="utf-8",
            )
            loaded = EvaluationDataset.load(path)
        self.assertEqual(loaded.dataset_id, "dataset-v1")
        self.assertEqual(loaded.cases[0].case_id, "one")

    @staticmethod
    def _case(
        case_id: str,
        *,
        expected: str = "STANDS",
        synthetic: bool = False,
    ) -> dict[str, object]:
        return {
            "case_id": case_id,
            "repository": "owner/repository",
            "decision_url": "https://github.com/owner/repository/blob/main/decision.md",
            "decision_ref": "main:decision.md",
            "ground_truth_url": "https://vendor.example.com/history",
            "ground_truth_source_type": "vendor_history",
            "ground_truth_effective_at": 1_700_000_000,
            "captured_at": 1_700_000_100,
            "source_sha256": "a" * 64,
            "expected_state": expected,
            "synthetic": synthetic,
            "notes": "Hand-checked source snapshot.",
        }


if __name__ == "__main__":
    unittest.main()
