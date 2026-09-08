"""Safe local archive inspection and restoration for Sibyl Memory.

The published Sibyl client can archive an entity but, as of 0.8.0, does not
expose a public restore operation. This module keeps the workaround narrow:
it only accepts the known SQLite schema, scopes every operation by tenant, and
restores one archive row atomically into the active ``entities`` table.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


ARCHIVE_COLUMNS = {
    "id",
    "tenant_id",
    "original_entity_id",
    "category",
    "name",
    "body",
    "archived_at",
    "archive_reason",
}
ENTITY_COLUMNS = {
    "id",
    "tenant_id",
    "category",
    "name",
    "status",
    "body",
    "created_at",
    "updated_at",
}


class ArchiveError(RuntimeError):
    """Base error for archive operations."""


class ArchiveConflictError(ArchiveError):
    """Raised when the active entity already exists."""


class ArchiveSchemaError(ArchiveError):
    """Raised when the database is not the expected Sibyl schema."""


@dataclass(frozen=True)
class ArchivedEntity:
    archive_id: str
    tenant_id: str
    original_entity_id: str | None
    category: str | None
    name: str | None
    body: Any | None
    archived_at: str
    archive_reason: str | None


@dataclass(frozen=True)
class RestoredEntity:
    entity_id: str
    tenant_id: str
    category: str
    name: str
    body: Any
    archive_id: str


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open a Sibyl SQLite database and reject an incompatible schema."""

    database = Path(path).expanduser()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        _require_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def list_archived(
    connection: sqlite3.Connection,
    tenant_id: str,
    *,
    category: str | None = None,
    name: str | None = None,
) -> list[ArchivedEntity]:
    """List archive rows for exactly one tenant."""

    clauses = ["tenant_id = ?"]
    parameters: list[str] = [tenant_id]
    if category is not None:
        clauses.append("category = ?")
        parameters.append(category)
    if name is not None:
        clauses.append("name = ?")
        parameters.append(name)
    query = (
        "SELECT id, tenant_id, original_entity_id, category, name, body, archived_at, archive_reason "
        "FROM archived_entities WHERE "
        + " AND ".join(clauses)
        + " ORDER BY archived_at DESC, id DESC"
    )
    rows = connection.execute(query, parameters).fetchall()
    return [_archive_from_row(row) for row in rows]


def restore_archived(
    connection: sqlite3.Connection,
    tenant_id: str,
    *,
    archive_id: str,
    overwrite: bool = False,
) -> RestoredEntity:
    """Restore one archive row atomically and remove that archive row.

    Existing active entities are protected by default. ``overwrite=True`` is
    explicit and updates the active row while preserving its existing ID.
    """

    with connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, tenant_id, original_entity_id, category, name, body, archived_at, archive_reason "
            "FROM archived_entities WHERE id = ? AND tenant_id = ?",
            (archive_id, tenant_id),
        ).fetchone()
        if row is None:
            raise ArchiveError("archive row not found for the requested tenant")

        archived = _archive_from_row(row)
        if not archived.category or not archived.name:
            raise ArchiveError("archive row has no restorable category/name")
        if archived.body is None:
            raise ArchiveError("archive row has no restorable body")
        try:
            json.loads(json.dumps(archived.body))
        except (TypeError, ValueError) as error:
            raise ArchiveError("archive row body is not valid JSON") from error

        active = connection.execute(
            "SELECT id FROM entities WHERE tenant_id = ? AND category = ? AND name = ?",
            (tenant_id, archived.category, archived.name),
        ).fetchone()
        if active is not None and not overwrite:
            raise ArchiveConflictError(
                f"active entity already exists for {archived.category}/{archived.name}"
            )

        entity_id = str(active["id"]) if active is not None else _available_entity_id(
            connection, archived.original_entity_id
        )
        body_json = json.dumps(archived.body, separators=(",", ":"), ensure_ascii=False)
        if active is None:
            connection.execute(
                "INSERT INTO entities (id, tenant_id, category, name, status, body) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                (entity_id, tenant_id, archived.category, archived.name, body_json),
            )
        else:
            connection.execute(
                "UPDATE entities SET status = NULL, body = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ? AND tenant_id = ?",
                (body_json, entity_id, tenant_id),
            )
        connection.execute(
            "DELETE FROM archived_entities WHERE id = ? AND tenant_id = ?",
            (archive_id, tenant_id),
        )
        return RestoredEntity(
            entity_id=entity_id,
            tenant_id=tenant_id,
            category=archived.category,
            name=archived.name,
            body=archived.body,
            archive_id=archive_id,
        )


def _require_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    required_tables = {"entities", "archived_entities"}
    if not required_tables.issubset(tables):
        missing = ", ".join(sorted(required_tables - tables))
        raise ArchiveSchemaError(f"missing Sibyl table(s): {missing}")
    for table, required_columns in (
        ("entities", ENTITY_COLUMNS),
        ("archived_entities", ARCHIVE_COLUMNS),
    ):
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not required_columns.issubset(columns):
            missing = ", ".join(sorted(required_columns - columns))
            raise ArchiveSchemaError(f"{table} is missing column(s): {missing}")


def _archive_from_row(row: sqlite3.Row) -> ArchivedEntity:
    if row["body"] is None:
        body = None
    else:
        try:
            body = json.loads(row["body"])
        except (TypeError, ValueError) as error:
            raise ArchiveError(f"archive row {row['id']} has invalid JSON body") from error
    return ArchivedEntity(
        archive_id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        original_entity_id=(str(row["original_entity_id"]) if row["original_entity_id"] else None),
        category=(str(row["category"]) if row["category"] is not None else None),
        name=(str(row["name"]) if row["name"] is not None else None),
        body=body,
        archived_at=str(row["archived_at"]),
        archive_reason=(str(row["archive_reason"]) if row["archive_reason"] is not None else None),
    )


def _available_entity_id(connection: sqlite3.Connection, original_id: str | None) -> str:
    if original_id:
        exists = connection.execute("SELECT 1 FROM entities WHERE id = ?", (original_id,)).fetchone()
        if exists is None:
            return original_id
    candidate = str(uuid.uuid4())
    while connection.execute("SELECT 1 FROM entities WHERE id = ?", (candidate,)).fetchone():
        candidate = str(uuid.uuid4())
    return candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to the Sibyl SQLite database")
    parser.add_argument("--tenant-id", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="List archive metadata")
    list_parser.add_argument("--category")
    list_parser.add_argument("--name")
    restore_parser = subparsers.add_parser("restore", help="Restore one archive row")
    restore_parser.add_argument("--archive-id", required=True)
    restore_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        connection = connect_database(args.db)
        try:
            if args.command == "list":
                rows = list_archived(connection, args.tenant_id, category=args.category, name=args.name)
                print(json.dumps([asdict(row) | {"body": None} for row in rows], indent=2))
            else:
                restored = restore_archived(
                    connection,
                    args.tenant_id,
                    archive_id=args.archive_id,
                    overwrite=args.overwrite,
                )
                print(json.dumps(asdict(restored), indent=2, ensure_ascii=False))
        finally:
            connection.close()
        return 0
    except (ArchiveError, FileNotFoundError, sqlite3.Error) as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
