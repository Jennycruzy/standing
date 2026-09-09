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


if __name__ == "__main__":
    unittest.main()
