import unittest
from datetime import date

from standing.temporal import (
    TemporalEvidence,
    TemporalObservation,
    TemporalObservationError,
    current,
    history,
    known_as_of,
    observation_evidence_hash,
    valid_as_of,
)


class TemporalEvidenceTests(unittest.TestCase):
    condition = "vendor.acme.retention_days"

    def test_strict_observation_round_trips_bitemporal_fields(self) -> None:
        raw = self._observation(
            "old",
            365,
            effective_from="2026-01-01",
            observed_at="2026-01-02T10:00:00Z",
            recorded_at="2026-01-02T10:01:00Z",
        )
        parsed = TemporalObservation.from_mapping(raw)

        self.assertTrue(parsed.is_bitemporal)
        self.assertTrue(parsed.is_complete)
        self.assertEqual(parsed.source_domain, "docs.acme.example")
        self.assertEqual(
            TemporalObservation.from_mapping(parsed.as_dict()).as_dict(),
            parsed.as_dict(),
        )

    def test_supersession_is_a_change_not_a_conflict(self) -> None:
        old = self._observation("old", 365, effective_from="2026-01-01", recorded_at="2026-01-02")
        new = self._observation(
            "new",
            90,
            effective_from="2026-09-07",
            observed_at="2026-09-08",
            recorded_at="2026-09-09",
            ref_uid="old",
        )
        evidence = TemporalEvidence.from_mappings([old, new])

        current_result = evidence.resolve(valid_at="2026-09-09")
        historical_result = evidence.resolve(valid_at="2026-03-03")

        self.assertFalse(current_result.conflict)
        self.assertEqual(current_result.current.observation_uid if current_result.current else None, "new")
        self.assertEqual(historical_result.current.observation_uid if historical_result.current else None, "old")
        self.assertEqual(current_result.superseded_uids, ("old",))
        self.assertEqual([item.observation_uid for item in current_result.history], ["old", "new"])

    def test_late_arriving_older_effective_period_does_not_override_current_head(self) -> None:
        old = self._observation("old", 365, effective_from="2026-01-01", recorded_at="2026-01-02")
        current_value = self._observation(
            "current",
            90,
            effective_from="2026-09-07",
            observed_at="2026-09-08",
            recorded_at="2026-09-09",
            ref_uid="old",
        )
        late_historical = self._observation(
            "late",
            180,
            effective_from="2026-02-01",
            observed_at="2026-09-10",
            recorded_at="2026-09-10",
        )

        selected = current(
            self.condition,
            [old, current_value, late_historical],
            as_of="2026-09-10",
            accepted_only=False,
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.observation_uid if selected else None, "current")

    def test_same_effective_period_is_genuine_conflict(self) -> None:
        first = self._observation("first", 90, effective_from="2026-09-07", recorded_at="2026-09-08")
        second = self._observation(
            "second",
            180,
            effective_from="2026-09-07",
            observed_at="2026-09-09",
            recorded_at="2026-09-09",
        )

        result = TemporalEvidence.from_mappings([first, second]).resolve(valid_at="2026-09-10")

        self.assertTrue(result.conflict)
        self.assertIsNone(result.current)
        self.assertEqual(result.conflicting_uids, ("first", "second"))

    def test_known_as_of_separates_what_was_true_from_what_was_known(self) -> None:
        old = self._observation("old", 365, effective_from="2026-01-01", recorded_at="2026-01-02")
        discovered_late = self._observation(
            "late",
            90,
            effective_from="2026-02-20",
            observed_at="2026-09-08",
            recorded_at="2026-09-09",
            ref_uid="old",
        )
        observations = [old, discovered_late]

        reconstructed = valid_as_of(
            self.condition,
            observations,
            date(2026, 3, 3),
            accepted_only=False,
        )
        known_then = known_as_of(
            self.condition,
            observations,
            date(2026, 3, 3),
            accepted_only=False,
        )

        self.assertEqual(reconstructed.value if reconstructed else None, 90)
        self.assertEqual(known_then.value if known_then else None, 365)

    def test_revoked_observation_is_not_a_current_head_but_remains_in_history(self) -> None:
        revoked = self._observation("revoked", 90, effective_from="2026-09-07", revoked=True)

        result = TemporalEvidence.from_mappings([revoked]).resolve(valid_at="2026-09-10")

        self.assertIsNone(result.current)
        self.assertEqual([item.observation_uid for item in result.history], ["revoked"])

    def test_revoked_successor_does_not_supersede_its_parent(self) -> None:
        old = self._observation("old", 365, effective_from="2026-01-01")
        revoked_successor = self._observation(
            "revoked-new",
            90,
            effective_from="2026-09-07",
            ref_uid="old",
            revoked=True,
        )

        result = TemporalEvidence.from_mappings([old, revoked_successor]).resolve(
            valid_at="2026-09-10"
        )

        self.assertEqual(result.current.observation_uid if result.current else None, "old")
        self.assertEqual(result.superseded_uids, ())
        self.assertEqual([item.observation_uid for item in result.history], ["old", "revoked-new"])

    def test_strict_records_require_knowledge_time(self) -> None:
        raw = self._observation("missing-recorded", 365)
        raw.pop("recorded_at")

        with self.assertRaisesRegex(TemporalObservationError, "recorded_at"):
            TemporalObservation.from_mapping(raw)

    def test_legacy_records_are_explicitly_ineligible_for_temporal_queries(self) -> None:
        legacy = {
            "condition_key": self.condition,
            "value": 365,
            "source_type": "vendor_primary",
            "observation_uid": "legacy",
        }
        evidence = TemporalEvidence.from_mappings([legacy], strict=False)

        self.assertFalse(evidence.is_bitemporal)
        with self.assertRaisesRegex(TemporalObservationError, "complete valid/knowledge time"):
            evidence.current(as_of="2026-09-10")

    def test_observation_hash_is_stable(self) -> None:
        payload = {"value": 365, "condition_key": self.condition}

        self.assertEqual(
            observation_evidence_hash(payload),
            observation_evidence_hash({"condition_key": self.condition, "value": 365}),
        )

    def test_accepted_only_requires_explicit_acceptance(self) -> None:
        pending = self._observation("pending", 365)
        accepted = self._observation("accepted", 90, effective_from="2026-09-07")
        accepted["accepted"] = True
        evidence = TemporalEvidence.from_mappings([pending, accepted])

        selected = evidence.current(as_of="2026-09-10", accepted_only=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.observation_uid if selected else None, "accepted")

        pending_only = TemporalEvidence.from_mappings([pending])
        self.assertIsNone(pending_only.current(as_of="2026-09-10", accepted_only=True))

    def test_product_facing_current_defaults_to_accepted_evidence(self) -> None:
        pending = self._observation("pending", 365)
        self.assertIsNone(current(self.condition, [pending], as_of="2026-09-10"))
        pending["accepted"] = True
        selected = current(self.condition, [pending], as_of="2026-09-10")
        self.assertEqual(selected.observation_uid if selected else None, "pending")

    def _observation(
        self,
        uid: str,
        value: int,
        *,
        effective_from: str = "2026-01-01",
        observed_at: str = "2026-01-02",
        recorded_at: str = "2026-01-02",
        ref_uid: str | None = None,
        revoked: bool = False,
    ) -> dict[str, object]:
        return {
            "condition_key": self.condition,
            "value": value,
            "value_type": "number",
            "unit": "days",
            "effective_from": effective_from,
            "observed_at": observed_at,
            "recorded_at": recorded_at,
            "source_url": "https://docs.acme.example/retention",
            "source_type": "vendor_primary",
            "attester": "attester:acme",
            "operator_id": "operator:acme",
            "extraction_method": "HTML_SELECTOR",
            "extraction_version": "retention-html-v1",
            "observation_uid": uid,
            "ref_uid": ref_uid,
            "evidence_hash": "a" * 64,
            "notes": "hand verified",
            "revoked": revoked,
        }


if __name__ == "__main__":
    unittest.main()
