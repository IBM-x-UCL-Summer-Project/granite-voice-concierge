import sqlite3
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
       print("MemoryStore: Table created successfully.")

    def create_memory(self, content, layer, event_time=None, strength=1, person=None, source_type=None, topic=None):
        self.cur.execute("INSERT INTO memories (content, layer, event_time, strength, person, source_type, topic) VALUES (?,     ?, ?, ?, ?, ?, ?)",
                         (content, layer, event_time, strength, person, source_type, topic))
        self.con.commit()
        print("MemoryStore: Memory created successfully.")
        return self.cur.lastrowid

    def get_memories(self, event_time=None, person=None, source_type=None, topic=None):
        query = "SELECT * FROM memories WHERE 1=1"
        params = []

        if event_time:
            query += " AND event_time = ?"
            params.append(event_time)
        if person:
            query += " AND person = ?"
            params.append(person)
        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        if topic:
            query += " AND topic = ?"
            params.append(topic)

        res = self.cur.execute(query, params)
        rows = res.fetchall()
        return [dict(row) for row in rows]



# memory_store = MemoryStore("memory.db")
# memory_store.create_memory("This is a test memory(0).", "test_layer", None, 1, None, None, None)
# memory_store.create_memory("This is a test memory(1).", "test_layer", None, 1, None, None, None)
# memory_store.create_memory("This is a test memory(2).", "test_layer", None, 1, "Kenny", None, None)
# memory_store.create_memory("This is a test memory(3).", "test_layer", None, 1, "Kenny", None, None)
# memory_store.create_memory("This is a test memory(4).", "test_layer", None, 1, "Kenny", None, None)
# memory_store.create_memory("This is a test memory(5).", "test_layer", None, 1, "Kenny", None, "cooking")
# memories_person = memory_store.get_memories(person="Kenny")
# memories_cooking = memory_store.get_memories(person="Kenny", topic="cooking")
# print(memories_person)
# print(memories_cooking)
