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
        self.cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS memories_memory_key_unique
            ON memories(memory_key)
            WHERE memory_key IS NOT NULL
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
        self.cur.execute(
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
        self.con.commit()
        return self.cur.lastrowid

    def get_memory_by_key(self, memory_key):
        """Get a single structured memory by its stable key."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE memory_key = ?", (memory_key,)
        ).fetchone()
        return dict(row) if row else None

    def get_memory_by_id(self, memory_id):
        """Get a single memory by ID. Returns None if not found."""
        row = self.cur.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_memories(self, person=None, source_type=None, topic=None, layer=None):
        query = "SELECT * FROM memories WHERE 1=1"
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

    def delete_memory(self, memory_id):
        self.cur.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.con.commit()
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

        query = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
        params.append(memory_id)

        self.cur.execute(query, params)
        self.con.commit()
        return self.cur.rowcount > 0
