import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.sibyl_archive import (
    ArchiveError,
    ArchiveConflictError,
    connect_database,
    list_archived,
    restore_archived,
)


SCHEMA = """
CREATE TABLE entities (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, category TEXT NOT NULL,
  name TEXT NOT NULL, status TEXT, body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT 'now', updated_at TEXT NOT NULL DEFAULT 'now',
  UNIQUE (tenant_id, category, name)
);
CREATE VIRTUAL TABLE entities_fts USING fts5(
  name, category, body, tenant_id UNINDEXED,
  content='entities', content_rowid='rowid'
);
CREATE TRIGGER entities_ai_fts AFTER INSERT ON entities BEGIN
  INSERT INTO entities_fts(rowid, name, category, body, tenant_id)
  VALUES (new.rowid, new.name, new.category, new.body, new.tenant_id);
END;
CREATE TABLE archived_entities (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, original_entity_id TEXT,
  category TEXT, name TEXT, body TEXT, archived_at TEXT NOT NULL DEFAULT 'now',
  archive_reason TEXT
);
"""


class SibylArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.path = Path(handle.name)
        connection = sqlite3.connect(self.path)
        connection.executescript(SCHEMA)
        entity_id = str(uuid.uuid4())
        archive_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO archived_entities (id, tenant_id, original_entity_id, category, name, body, archive_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (archive_id, "tenant-a", entity_id, "project", "standing", json.dumps({"status": "ready"}), "test"),
        )
        connection.commit()
        connection.close()
        self.archive_id = archive_id
        self.entity_id = entity_id

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_list_is_tenant_scoped_and_restore_is_atomic(self) -> None:
        connection = connect_database(self.path)
        self.assertEqual(len(list_archived(connection, "tenant-a")), 1)
        self.assertEqual(list_archived(connection, "tenant-b"), [])
        restored = restore_archived(connection, "tenant-a", archive_id=self.archive_id)
        self.assertEqual(restored.entity_id, self.entity_id)
        self.assertEqual(restored.body, {"status": "ready"})
        self.assertEqual(list_archived(connection, "tenant-a"), [])
        row = connection.execute("SELECT body FROM entities WHERE id = ?", (self.entity_id,)).fetchone()
        self.assertEqual(json.loads(row[0]), {"status": "ready"})
        fts_match = connection.execute(
            "SELECT count(*) FROM entities_fts WHERE entities_fts MATCH ?", ("standing",)
        ).fetchone()[0]
        self.assertEqual(fts_match, 1)
        connection.close()

    def test_existing_active_entity_requires_explicit_overwrite(self) -> None:
        connection = connect_database(self.path)
        connection.execute(
            "INSERT INTO entities (id, tenant_id, category, name, status, body) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "tenant-a", "project", "standing", "active", "{}"),
        )
        connection.commit()
        with self.assertRaises(ArchiveConflictError):
            restore_archived(connection, "tenant-a", archive_id=self.archive_id)
        self.assertEqual(len(list_archived(connection, "tenant-a")), 1)
        connection.close()

    def test_invalid_archive_json_fails_closed(self) -> None:
        connection = connect_database(self.path)
        connection.execute(
            "INSERT INTO archived_entities (id, tenant_id, category, name, body, archive_reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "tenant-a", "project", "broken", "not-json", "test"),
        )
        connection.commit()
        with self.assertRaises(ArchiveError):
            list_archived(connection, "tenant-a")
        self.assertEqual(connection.execute("SELECT count(*) FROM entities").fetchone()[0], 0)
        connection.close()


if __name__ == "__main__":
    unittest.main()
