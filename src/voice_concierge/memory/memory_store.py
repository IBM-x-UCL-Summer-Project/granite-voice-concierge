import sqlite3
import time
from pathlib import Path


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
        self.con.commit()

    def create_memory(self, content, layer, event_time=None, strength=1,
                      person=None, source_type=None, topic=None):
        created_at = int(time.time())
        self.cur.execute(
            """
            INSERT INTO memories
            (content, layer, created_at, event_time, strength, person, source_type, topic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content, layer, created_at, event_time, strength, person, source_type, topic),
        )
        self.con.commit()
        return self.cur.lastrowid

    def get_memories(self, person=None, source_type=None, topic=None):
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

        query += " ORDER BY created_at DESC"
        rows = self.cur.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self.con.close()

    def delete_memory(self, memory_id):
        self.cur.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.con.commit()
        return self.cur.rowcount > 0

    def update_memory(self,memory_id, content=None, layer=None, event_time=None, strength=None,
                      person=None, source_type=None, topic=None):
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
