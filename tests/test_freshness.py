import unittest

from standing.freshness import check_freshness


class FreshnessTests(unittest.TestCase):
    def test_recent_timestamp_is_fresh(self) -> None:
        result = check_freshness(
            [{"observation_uid": "0xone", "effective_from": 900}],
            now_unix=1_000,
            max_age_seconds=100,
        )

        self.assertTrue(result.fresh)
        self.assertEqual(result.reasons, ())

    def test_old_or_missing_timestamp_requires_revalidation(self) -> None:
        result = check_freshness(
            [
                {"observation_uid": "0xold", "effective_from": 1},
                {"observation_uid": "0xmissing"},
            ],
            now_unix=1_000,
            max_age_seconds=100,
        )

        self.assertFalse(result.fresh)
        self.assertEqual(result.stale_observation_uids, ("0xold",))
        self.assertEqual(result.missing_timestamp_uids, ("0xmissing",))
        self.assertEqual(len(result.reasons), 2)

    def test_future_timestamp_is_not_accepted_as_fresh(self) -> None:
        result = check_freshness(
            [{"observation_uid": "0xfuture", "effective_from": 1_001}],
            now_unix=1_000,
            max_age_seconds=100,
        )

        self.assertFalse(result.fresh)
        self.assertEqual(result.future_timestamp_uids, ("0xfuture",))

    def test_knowledge_time_controls_freshness_not_effective_time(self) -> None:
        result = check_freshness(
            [
                {
                    "observation_uid": "0xhistorical",
                    "effective_from": 1,
                    "observed_at": 995,
                    "recorded_at": 1_000,
                }
            ],
            now_unix=1_000,
            max_age_seconds=100,
        )

        self.assertTrue(result.fresh)

    def test_scheduled_recheck_is_due_at_the_configured_interval(self) -> None:
        result = check_freshness(
            [{"observation_uid": "0xdue", "recorded_at": 900}],
            now_unix=1_000,
            max_age_seconds=500,
            recheck_interval_seconds=100,
        )

        self.assertFalse(result.fresh)
        self.assertEqual(result.scheduled_recheck_uids, ("0xdue",))
        self.assertIn("scheduled revalidation", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
