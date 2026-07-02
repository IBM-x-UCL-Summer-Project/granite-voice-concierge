from pathlib import Path

import pysqlite3 as sqlite3
import sqlite_vec
from sqlite_vec import serialize_float32


class VectorStore:
    def __init__(self, db_path, dimension=768):
        self.db_path = Path(db_path)
        self.dimension = dimension

        self.con = sqlite3.connect(self.db_path)
        self._load_sqlite_vec()
        self._create_vector_table()

    def _load_sqlite_vec(self):
        if not hasattr(self.con, "enable_load_extension"):
            raise RuntimeError(
                "This SQLite connection does not support extension loading."
            )

        self.con.enable_load_extension(True)
        sqlite_vec.load(self.con)
        self.con.enable_load_extension(False)

    def _create_vector_table(self):
        self.con.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors
            USING vec0(
                memory_id INTEGER PRIMARY KEY,
                embedding float[{self.dimension}]
            )
            """
        )
        self.con.commit()

    def save_vector(self, memory_id, embedding):
        if len(embedding) != self.dimension:
            raise ValueError(
                f"Expected embedding dimension {self.dimension}, "
                f"got {len(embedding)}."
            )

        # Delete existing vector if it exists (sqlite_vec doesn't support REPLACE)
        self.con.execute(
            "DELETE FROM memory_vectors WHERE memory_id = ?",
            (memory_id,),
        )

        self.con.execute(
            """
            INSERT INTO memory_vectors
            (memory_id, embedding)
            VALUES (?, ?)
            """,
            (memory_id, serialize_float32(embedding)),
        )
        self.con.commit()

    def search_similar(self, query_embedding, top_k=3):
        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Expected query dimension {self.dimension}, "
                f"got {len(query_embedding)}."
            )

        rows = self.con.execute(
            """
            SELECT memory_id, distance
            FROM memory_vectors
            WHERE embedding MATCH ?
              AND k = ?
            ORDER BY distance
            """,
            (serialize_float32(query_embedding), top_k),
        ).fetchall()

        return [
            {
                "memory_id": row[0],
                "distance": row[1],
            }
            for row in rows
        ]

    def close(self):
        self.con.close()
