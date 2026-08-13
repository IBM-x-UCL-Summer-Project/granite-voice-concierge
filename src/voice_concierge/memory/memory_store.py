import time
from collections.abc import Sequence
from pathlib import Path

import pysqlite3 as sqlite3

from voice_concierge.memory.types import (
    MemoryRecord,
    MemoryScope,
    MemoryUpdate,
    MemoryWrite,
    normalize_event_time,
    normalize_memory_strength,
)


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self._create_table()

    def _create_table(self) -> None:
        schema_path = Path(__file__).parent / "memory.sql"
        sql = schema_path.read_text()
        self.cur.executescript(sql)
        columns = {
            row["name"]
            for row in self.cur.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "memory_key" not in columns:
            self.cur.execute("ALTER TABLE memories ADD COLUMN memory_key TEXT")
        if "revision" not in columns:
            self.cur.execute(
                "ALTER TABLE memories ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
            )
        if "indexed_revision" not in columns:
            self.cur.execute(
                "ALTER TABLE memories ADD COLUMN indexed_revision "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "deleted_at" not in columns:
            self.cur.execute("ALTER TABLE memories ADD COLUMN deleted_at INTEGER")
        self._migrate_legacy_values()
        self.cur.execute("DROP INDEX IF EXISTS memories_memory_key_unique")
        self.cur.execute("""
            CREATE UNIQUE INDEX memories_memory_key_unique
            ON memories(memory_key)
            WHERE memory_key IS NOT NULL AND deleted_at IS NULL
            """)
        self.con.commit()

    def _migrate_legacy_values(self) -> None:
        """Normalize values written before storage-boundary validation existed."""

        rows = self.cur.execute(
            "SELECT id, event_time, strength, memory_key, person, source_type, topic "
            "FROM memories"
        ).fetchall()
        for row in rows:
            normalized_values = (
                normalize_event_time(row["event_time"]),
                normalize_memory_strength(row["strength"], default=5),
                _legacy_optional_text(row["memory_key"]),
                _legacy_optional_text(row["person"]),
                _legacy_optional_text(row["source_type"]),
                _legacy_optional_text(row["topic"]),
            )
            current_values = tuple(
                row[field]
                for field in (
                    "event_time",
                    "strength",
                    "memory_key",
                    "person",
                    "source_type",
                    "topic",
                )
            )
            if normalized_values == current_values:
                continue
            self.cur.execute(
                """
                UPDATE memories
                SET event_time = ?,
                    strength = ?,
                    memory_key = ?,
                    person = ?,
                    source_type = ?,
                    topic = ?
                WHERE id = ?
                """,
                (*normalized_values, row["id"]),
            )

    def create_memory(
        self,
        content: str,
        layer: str,
        event_time: int | None = None,
        strength: int = 1,
        person: str | None = None,
        source_type: str | None = None,
        topic: str | None = None,
        memory_key: str | None = None,
    ) -> int:
        memory = MemoryWrite(
            content=content,
            layer=layer,
            memory_key=memory_key,
            event_time=event_time,
            strength=strength,
            person=person,
            source_type=source_type,
            topic=topic,
        )
        created_at = int(time.time())
        self._commit_statement(
            """
            INSERT INTO memories
            (
                content,
                layer,
                memory_key,
                created_at,
                event_time,
                strength,
                person,
                source_type,
                topic
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.content,
                memory.layer,
                memory.memory_key,
                created_at,
                memory.event_time,
                memory.strength,
                memory.person,
                memory.source_type,
                memory.topic,
            ),
        )
        memory_id = self.cur.lastrowid
        if memory_id is None:
            raise RuntimeError("SQLite did not return an ID for the new memory.")
        return memory_id

    def get_memory_by_key(self, memory_key: str) -> MemoryRecord | None:
        """Get a single structured memory by its stable key."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE memory_key = ? AND deleted_at IS NULL",
            (memory_key,),
        ).fetchone()
        return MemoryRecord.from_mapping(row) if row else None

    def get_memory_by_id(self, memory_id: int) -> MemoryRecord | None:
        """Get a single memory by ID. Returns None if not found."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        ).fetchone()
        return MemoryRecord.from_mapping(row) if row else None

    def get_memory_by_id_including_deleted(
        self,
        memory_id: int,
    ) -> MemoryRecord | None:
        """Get a memory regardless of tombstone state for recovery checks."""

        row = self.cur.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return MemoryRecord.from_mapping(row) if row else None

    def get_memories(
        self,
        person: str | None = None,
        source_type: str | None = None,
        topic: str | None = None,
        layer: str | None = None,
    ) -> list[MemoryRecord]:
        query = "SELECT * FROM memories WHERE deleted_at IS NULL"
        params = []

        if person is not None:
            query += " AND person = ?"
            params.append(person)
        if source_type is not None:
            query += " AND source_type = ?"
            params.append(source_type)
        if topic is not None:
            query += " AND topic = ?"
            params.append(topic)
        if layer is not None:
            query += " AND layer = ?"
            params.append(layer)

        query += " ORDER BY created_at DESC"
        rows = self.cur.execute(query, params).fetchall()
        return [MemoryRecord.from_mapping(row) for row in rows]

    def get_memories_in_scope(self, scope: MemoryScope) -> list[MemoryRecord]:
        """Return active records in one exact metadata scope.

        Unlike the optional filters in :meth:`get_memories`, ``None`` is a
        meaningful scope value here rather than a wildcard.
        """

        if not isinstance(scope, MemoryScope):
            raise TypeError("Exact memory lookup requires a MemoryScope.")
        rows = self.cur.execute(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL
              AND layer = ?
              AND person IS ?
              AND source_type IS ?
              AND topic IS ?
            ORDER BY created_at DESC, id DESC
            """,
            (
                scope.layer,
                scope.person,
                scope.source_type,
                scope.topic,
            ),
        ).fetchall()
        return [MemoryRecord.from_mapping(row) for row in rows]

    def close(self) -> None:
        self.con.close()

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> bool:
        """Logically delete a record while preserving cleanup recovery state."""

        return self.tombstone_memory(memory_id, expected_revision)

    def tombstone_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> bool:
        """Hide a record atomically before best-effort vector cleanup."""

        query = "UPDATE memories SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL"
        params: list[object] = [int(time.time()), memory_id]
        if expected_revision is not None:
            query += " AND revision = ?"
            params.append(expected_revision)
        self._commit_statement(query, params)
        return self.cur.rowcount > 0

    def purge_tombstone(self, memory_id: int) -> bool:
        """Hard-delete a record only after its derived index entry is gone."""

        self._commit_statement(
            "DELETE FROM memories WHERE id = ? AND deleted_at IS NOT NULL",
            (memory_id,),
        )
        return self.cur.rowcount > 0

    def update_memory(
        self,
        memory_id: int,
        content: str | None = None,
        layer: str | None = None,
        event_time: int | None = None,
        strength: int | None = None,
        person: str | None = None,
        source_type: str | None = None,
        topic: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        memory = MemoryUpdate(
            content=content,
            layer=layer,
            event_time=event_time,
            strength=strength,
            person=person,
            source_type=source_type,
            topic=topic,
        )
        if not memory.has_changes:
            return False

        updates = []
        params: list[object] = []

        if memory.content is not None:
            updates.append("content = ?")
            params.append(memory.content)
        if memory.layer is not None:
            updates.append("layer = ?")
            params.append(memory.layer)
        if memory.event_time is not None:
            updates.append("event_time = ?")
            params.append(memory.event_time)
        if memory.strength is not None:
            updates.append("strength = ?")
            params.append(memory.strength)
        if memory.person is not None:
            updates.append("person = ?")
            params.append(memory.person)
        if memory.source_type is not None:
            updates.append("source_type = ?")
            params.append(memory.source_type)
        if memory.topic is not None:
            updates.append("topic = ?")
            params.append(memory.topic)

        updates.append("revision = revision + 1")
        query = (
            f"UPDATE memories SET {', '.join(updates)} "
            "WHERE id = ? AND deleted_at IS NULL"
        )
        params.append(memory_id)
        if expected_revision is not None:
            query += " AND revision = ?"
            params.append(expected_revision)

        self._commit_statement(query, params)
        return self.cur.rowcount > 0

    def mark_memory_indexed(self, memory_id: int, revision: int) -> bool:
        """Record that the vector index matches one still-current revision."""

        self._commit_statement(
            """
            UPDATE memories
            SET indexed_revision = ?
            WHERE id = ? AND revision = ? AND deleted_at IS NULL
            """,
            (revision, memory_id, revision),
        )
        return self.cur.rowcount > 0

    def get_memories_needing_index(self) -> list[MemoryRecord]:
        """Return active records whose derived vector is stale or missing."""

        rows = self.cur.execute("""
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND indexed_revision != revision
            ORDER BY id
            """).fetchall()
        return [MemoryRecord.from_mapping(row) for row in rows]

    def get_tombstoned_memories(self) -> list[MemoryRecord]:
        """Return records awaiting derived-vector cleanup."""

        rows = self.cur.execute(
            "SELECT * FROM memories WHERE deleted_at IS NOT NULL ORDER BY id"
        ).fetchall()
        return [MemoryRecord.from_mapping(row) for row in rows]

    def get_all_memory_ids(self) -> set[int]:
        """Return active and tombstoned IDs for orphan-index reconciliation."""

        rows = self.cur.execute("SELECT id FROM memories").fetchall()
        return {row["id"] for row in rows}

    def _commit_statement(
        self,
        query: str,
        params: Sequence[object],
    ) -> None:
        """Commit one SQL write or roll its transaction back on failure."""

        try:
            self.cur.execute(query, params)
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise


def _legacy_optional_text(value: object) -> str | None:
    """Preserve usable legacy text and clear invalid optional metadata."""

    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
