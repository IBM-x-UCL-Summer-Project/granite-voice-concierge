import time
from pathlib import Path

import pysqlite3 as sqlite3


class MemoryStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self._create_table()

    def _create_table(self):
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
        self.cur.execute("DROP INDEX IF EXISTS memories_memory_key_unique")
        self.cur.execute("""
            CREATE UNIQUE INDEX memories_memory_key_unique
            ON memories(memory_key)
            WHERE memory_key IS NOT NULL AND deleted_at IS NULL
            """)
        self.con.commit()

    def create_memory(
        self,
        content,
        layer,
        event_time=None,
        strength=1,
        person=None,
        source_type=None,
        topic=None,
        memory_key=None,
    ):
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
                content,
                layer,
                memory_key,
                created_at,
                event_time,
                strength,
                person,
                source_type,
                topic,
            ),
        )
        return self.cur.lastrowid

    def get_memory_by_key(self, memory_key):
        """Get a single structured memory by its stable key."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE memory_key = ? AND deleted_at IS NULL",
            (memory_key,),
        ).fetchone()
        return dict(row) if row else None

    def get_memory_by_id(self, memory_id):
        """Get a single memory by ID. Returns None if not found."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_memory_by_id_including_deleted(self, memory_id):
        """Get a memory regardless of tombstone state for recovery checks."""

        row = self.cur.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_memories(self, person=None, source_type=None, topic=None, layer=None):
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
        return [dict(row) for row in rows]

    def close(self):
        self.con.close()

    def delete_memory(self, memory_id, expected_revision=None):
        """Logically delete a record while preserving cleanup recovery state."""

        return self.tombstone_memory(memory_id, expected_revision)

    def tombstone_memory(self, memory_id, expected_revision=None):
        """Hide a record atomically before best-effort vector cleanup."""

        query = "UPDATE memories SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL"
        params = [int(time.time()), memory_id]
        if expected_revision is not None:
            query += " AND revision = ?"
            params.append(expected_revision)
        self._commit_statement(query, params)
        return self.cur.rowcount > 0

    def purge_tombstone(self, memory_id):
        """Hard-delete a record only after its derived index entry is gone."""

        self._commit_statement(
            "DELETE FROM memories WHERE id = ? AND deleted_at IS NOT NULL",
            (memory_id,),
        )
        return self.cur.rowcount > 0

    def update_memory(
        self,
        memory_id,
        content=None,
        layer=None,
        event_time=None,
        strength=None,
        person=None,
        source_type=None,
        topic=None,
        expected_revision=None,
    ):
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if layer is not None:
            updates.append("layer = ?")
            params.append(layer)
        if event_time is not None:
            updates.append("event_time = ?")
            params.append(event_time)
        if strength is not None:
            updates.append("strength = ?")
            params.append(strength)
        if person is not None:
            updates.append("person = ?")
            params.append(person)
        if source_type is not None:
            updates.append("source_type = ?")
            params.append(source_type)
        if topic is not None:
            updates.append("topic = ?")
            params.append(topic)

        if not updates:
            return False

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

    def mark_memory_indexed(self, memory_id, revision):
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

    def get_memories_needing_index(self):
        """Return active records whose derived vector is stale or missing."""

        rows = self.cur.execute("""
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND indexed_revision != revision
            ORDER BY id
            """).fetchall()
        return [dict(row) for row in rows]

    def get_tombstoned_memories(self):
        """Return records awaiting derived-vector cleanup."""

        rows = self.cur.execute(
            "SELECT * FROM memories WHERE deleted_at IS NOT NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_all_memory_ids(self):
        """Return active and tombstoned IDs for orphan-index reconciliation."""

        rows = self.cur.execute("SELECT id FROM memories").fetchall()
        return {row["id"] for row in rows}

    def _commit_statement(self, query, params):
        """Commit one SQL write or roll its transaction back on failure."""

        try:
            self.cur.execute(query, params)
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise
