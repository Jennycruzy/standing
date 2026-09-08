import unittest

from standing.evaluator import StandingState, evaluate_standing


class EvaluatorTests(unittest.TestCase):
    def test_all_four_supported_predicates_can_stand(self) -> None:
        decision = {
            "decision_id": "event-persistence",
            "conditions": [
                self._spec("vendor.acme.retention_days", "retention_days >= 365"),
                self._spec("vendor.acme.regions", 'regions contains "eu-central"'),
                self._spec("vendor.acme.sso", "supports_sso == true"),
                self._spec("vendor.acme.eol", "eol_date > 2027-01-01"),
            ],
        }
        conditions = {
            "vendor.acme.retention_days": {"accepted_value": 365},
            "vendor.acme.regions": {"accepted_value": ["eu-central", "us-east"]},
            "vendor.acme.sso": {"accepted_value": True},
            "vendor.acme.eol": {"accepted_value": "2027-01-02"},
        }

        result = evaluate_standing(decision, conditions)

        self.assertEqual(result.state, StandingState.STANDS)
        self.assertTrue(all(condition.state == StandingState.STANDS for condition in result.conditions))
        self.assertTrue(all(not condition.blocks for condition in result.conditions))

    def test_failed_required_condition_expires_the_decision(self) -> None:
        result = evaluate_standing(
            {
                "id": "event-persistence",
                "conditions": [self._spec("vendor.acme.retention_days", "retention_days >= 365")],
            },
            {"vendor.acme.retention_days": {"accepted_value": 90}},
        )

        self.assertEqual(result.state, StandingState.EXPIRED)
        self.assertTrue(result.conditions[0].blocks)

    def test_missing_value_is_unknown(self) -> None:
        result = evaluate_standing(
            {
                "name": "event-persistence",
                "conditions": [self._spec("vendor.acme.retention_days", "retention_days >= 365")],
            },
            {},
        )

        self.assertEqual(result.state, StandingState.UNKNOWN)
        self.assertTrue(result.conditions[0].blocks)

    def test_disagreement_is_contested(self) -> None:
        result = evaluate_standing(
            {
                "decision_id": "event-persistence",
                "conditions": [self._spec("vendor.acme.retention_days", "retention_days >= 365")],
            },
            {
                "vendor.acme.retention_days": {
                    "accepted_value": 365,
                    "acceptance_status": "CONTESTED",
                    "observations": [
                        {"value": 365, "observation_uid": "0xaaa"},
                        {"value": 90, "observation_uid": "0xbbb"},
                    ],
                }
            },
        )

        self.assertEqual(result.state, StandingState.CONTESTED)
        self.assertEqual(result.conditions[0].observation_uids, ("0xaaa", "0xbbb"))

    def test_inferred_failure_is_visible_but_cannot_block(self) -> None:
        result = evaluate_standing(
            {
                "decision_id": "event-persistence",
                "conditions": [
                    self._spec(
                        "vendor.acme.retention_days",
                        "retention_days >= 365",
                        provenance="INFERRED",
                    )
                ],
            },
            {"vendor.acme.retention_days": {"accepted_value": 90}},
        )

        self.assertEqual(result.state, StandingState.STANDS)
        self.assertEqual(result.conditions[0].state, StandingState.EXPIRED)
        self.assertFalse(result.conditions[0].blocks)
        self.assertIn("cannot block", result.conditions[0].message)

    def test_unsupported_rule_is_a_note(self) -> None:
        result = evaluate_standing(
            {
                "decision_id": "event-persistence",
                "conditions": [self._spec("vendor.acme.price", "price <= 2500")],
            },
            {"vendor.acme.price": {"accepted_value": 5000}},
        )

        self.assertEqual(result.state, StandingState.STANDS)
        self.assertFalse(result.conditions[0].evaluated)
        self.assertFalse(result.conditions[0].blocks)
        self.assertIn("cannot block", result.conditions[0].message)

    def test_fingerprint_is_stable_when_mapping_order_changes(self) -> None:
        decision = {
            "decision_id": "event-persistence",
            "conditions": [self._spec("vendor.acme.retention_days", "retention_days >= 365")],
        }
        first = evaluate_standing(
            decision,
            {"vendor.acme.retention_days": {"accepted_value": 365, "source_url": "https://vendor.example"}},
        )
        second = evaluate_standing(
            decision,
            {"vendor.acme.retention_days": {"source_url": "https://vendor.example", "accepted_value": 365}},
        )

        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 64)
        self.assertEqual(first.as_dict()["fingerprint"], first.fingerprint)

    @staticmethod
    def _spec(key: str, predicate: str, *, provenance: str = "CONFIRMED") -> dict[str, object]:
        return {
            "condition_key": key,
            "predicate": predicate,
            "provenance": provenance,
            "required": True,
        }


if __name__ == "__main__":
    unittest.main()
