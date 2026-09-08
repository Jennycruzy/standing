import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sibyl_memory_client.exceptions import NotFoundError

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
            if "MEMORY" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(files_with_flag, [source_root / "memory.py"])


if __name__ == "__main__":
    unittest.main()
