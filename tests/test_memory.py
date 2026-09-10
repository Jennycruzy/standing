import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sibyl_memory_client.exceptions import NotFoundError

from standing.lifecycle import DecisionRevision, Remediation, Waiver
from standing.memory import create_memory_store


class MemoryLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "standing.db"
        self.store = create_memory_store(path=self.path, tenant_id="phase-1")

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_round_trip_covers_all_active_tiers_and_governed_path_search(self) -> None:
        decision = {
            "title": "Use Acme for event persistence",
            "governed_paths": ["src/events/archive.py", "infra/acme.tf"],
            "conditions": ["vendor.acme.retention_days"],
        }
        first = self.store.save_decision("acme-events", decision)
        second = self.store.save_decision("acme-events", {**decision, "title": "Updated title"})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.client.list_entities(category="decision")), 1)
        self.assertEqual(self.store.read_decision("acme-events")["body"]["title"], "Updated title")

        self.store.save_condition(
            "vendor.acme.retention_days",
            {"accepted_value": 365, "source_url": "https://vendor.example/retention"},
        )
        self.store.save_observer(
            "0x1111111111111111111111111111111111111111",
            {"readings_confirmed": 3, "readings_contradicted": 0},
        )
        self.store.save_observation(
            "0xobservation",
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 365,
                "source_type": "verifier",
                "observer_address": "0x1111111111111111111111111111111111111111",
                "observation_uid": "0xobservation",
            },
        )
        self.store.save_standing("acme-events", {"state": "STANDS"})
        self.store.save_condition_reference(
            "vendor.acme.retention_days",
            {"value": 365, "source_url": "https://vendor.example/retention"},
            metadata={"observation_uid": "0xabc"},
        )
        self.store.record_standing_change(
            evaluated={"decision_id": "acme-events", "state": "STANDS"},
            acted={"action": "none"},
            forward={"next": "recheck"},
            extra={"observation_uid": "0xabc"},
        )

        self.assertEqual(self.store.read_condition("vendor.acme.retention_days")["body"]["accepted_value"], 365)
        self.assertEqual(self.store.read_observer("0x1111111111111111111111111111111111111111")["body"]["readings_confirmed"], 3)
        self.assertEqual(
            self.store.list_observations("vendor.acme.retention_days")[0]["value"],
            365,
        )
        self.assertEqual(self.store.read_standing("acme-events")["state"], "STANDS")
        reference = self.store.read_condition_reference("vendor.acme.retention_days")
        self.assertIsNotNone(reference)
        self.assertEqual(reference["body"]["value"], 365)
        self.assertEqual(len(self.store.client.read_events()), 1)
        matches = self.store.search_decisions(["src/events/archive.py"])
        self.assertEqual([match["key"] for match in matches], ["acme-events"])

    def test_archive_and_restore_preserve_the_decision(self) -> None:
        self.store.save_decision("old-decision", {"governed_paths": ["src/old.py"]})
        archived = self.store.archive_decision("old-decision", reason="expired")
        with self.assertRaises(NotFoundError):
            self.store.read_decision("old-decision")

        restored = self.store.restore_decision(archived["archived_id"])
        self.assertEqual(restored["name"], "old-decision")
        self.assertEqual(restored["body"]["governed_paths"], ["src/old.py"])

    def test_temporal_observation_queries_are_available_through_memory(self) -> None:
        self.store.save_observation(
            "old",
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 365,
                "value_type": "number",
                "unit": "days",
                "effective_from": "2026-01-01",
                "observed_at": "2026-01-02",
                "recorded_at": "2026-01-02",
                "source_url": "https://docs.acme.example/retention",
                "source_type": "vendor_primary",
                "attester": "attester:acme",
                "operator_id": "operator:acme",
                "extraction_method": "HTML_SELECTOR",
                "extraction_version": "retention-html-v1",
                "observation_uid": "old",
                "evidence_hash": "a" * 64,
                "notes": "initial reading",
                "accepted": True,
            },
        )
        self.store.save_observation(
            "new",
            {
                "condition_key": "vendor.acme.retention_days",
                "value": 90,
                "value_type": "number",
                "unit": "days",
                "effective_from": "2026-09-07",
                "observed_at": "2026-09-08",
                "recorded_at": "2026-09-09",
                "source_url": "https://docs.acme.example/retention",
                "source_type": "vendor_primary",
                "attester": "attester:acme",
                "operator_id": "operator:acme",
                "extraction_method": "HTML_SELECTOR",
                "extraction_version": "retention-html-v1",
                "observation_uid": "new",
                "ref_uid": "old",
                "evidence_hash": "b" * 64,
                "notes": "superseding reading",
                "accepted": True,
            },
        )

        self.assertEqual(
            self.store.current_observation(
                "vendor.acme.retention_days",
                as_of="2026-09-09",
            ).value,
            90,
        )
        self.assertEqual(
            self.store.valid_observation_as_of(
                "vendor.acme.retention_days",
                "2026-03-03",
            ).value,
            365,
        )
        self.assertEqual(
            self.store.known_observation_as_of(
                "vendor.acme.retention_days",
                "2026-03-03",
            ).value,
            365,
        )
        self.assertEqual(
            [item.observation_uid for item in self.store.observation_history("vendor.acme.retention_days")],
            ["old", "new"],
        )

    def test_observation_uid_is_immutable_except_for_acceptance_metadata(self) -> None:
        body = {
            "condition_key": "vendor.acme.retention_days",
            "value": 365,
            "source_type": "vendor_primary",
            "observation_uid": "immutable-observation",
        }

        first = self.store.save_observation("immutable-observation", body)
        replay = self.store.save_observation("immutable-observation", dict(body))
        self.assertEqual(replay, first)

        accepted = self.store.save_observation(
            "immutable-observation",
            {**body, "accepted": True},
        )
        self.assertTrue(accepted["body"]["accepted"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.store.save_observation(
                "immutable-observation",
                {**body, "value": 90},
            )

    def test_lifecycle_records_round_trip_through_dedicated_categories_and_journal(self) -> None:
        revision = DecisionRevision.from_mapping(
            {
                "decision_id": "lifecycle-decision",
                "revision_id": "r1",
                "effective_from": 100,
                "body": {"title": "Keep the old path"},
            }
        )
        remediation = Remediation.create(
            "rem-1",
            "lifecycle-decision",
            "r1",
            opened_at=100,
            summary="Recheck the dependency.",
        )
        waiver = Waiver(
            "waiver-1",
            "lifecycle-decision",
            None,
            "Incident commander accepted the temporary exception.",
            "alice",
            "human",
            100,
            200,
        )

        self.store.save_decision_revision(revision)
        self.store.save_remediation(remediation)
        self.store.save_waiver(waiver)
        self.store.record_lifecycle_event(
            event_type="waiver_issued",
            decision_id="lifecycle-decision",
            acted={"action": "waive"},
            forward={"waiver_id": "waiver-1"},
            ts="2026-01-01T00:00:01Z",
        )

        self.assertEqual(self.store.read_decision_revision("r1")["body"]["revision_id"], "r1")
        self.assertEqual(self.store.list_decision_revisions("lifecycle-decision")[0]["name"], "r1")
        self.assertEqual(self.store.read_remediation("rem-1")["body"]["status"], "OPEN")
        self.assertEqual(self.store.list_remediations("lifecycle-decision")[0]["name"], "rem-1")
        self.assertEqual(self.store.read_waiver("waiver-1")["body"]["issued_by"], "alice")
        self.assertEqual(self.store.list_waivers("lifecycle-decision")[0]["name"], "waiver-1")
        self.assertEqual(self.store.read_standing_changes()[0]["extra"]["event_type"], "waiver_issued")

    def test_memory_off_uses_the_same_interface_but_starts_empty(self) -> None:
        with patch.dict(os.environ, {"MEMORY": "off"}):
            empty_store = create_memory_store(path=self.path, tenant_id="phase-1")
            try:
                empty_store.save_decision("temporary", {"governed_paths": ["src/temp.py"]})
                self.assertEqual(empty_store.read_decision("temporary")["name"], "temporary")
            finally:
                empty_store.close()

            fresh_empty_store = create_memory_store(path=self.path, tenant_id="phase-1")
            try:
                with self.assertRaises(NotFoundError):
                    fresh_empty_store.read_decision("temporary")
            finally:
                fresh_empty_store.close()

    def test_memory_flag_is_read_in_one_source_file(self) -> None:
        source_root = Path(__file__).parents[1] / "standing"
        files_with_flag = [
            path
            for path in source_root.glob("*.py")
            if 'os.environ.get("MEMORY")' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(files_with_flag, [source_root / "memory.py"])


if __name__ == "__main__":
    unittest.main()
