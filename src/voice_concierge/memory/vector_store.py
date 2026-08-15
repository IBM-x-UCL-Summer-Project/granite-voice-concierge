from collections.abc import Sequence
from pathlib import Path

import pysqlite3 as sqlite3
import sqlite_vec
from sqlite_vec import serialize_float32

from voice_concierge.memory.types import VectorSearchResult


class VectorStore:
    def __init__(self, db_path: str | Path, dimension: int = 768) -> None:
        self.db_path = Path(db_path)
        self.dimension = dimension

        # See MemoryStore: access is serialized by MemoryManagerGateway, while
        # a web transport is free to execute different turns on worker threads.
        self.con = sqlite3.connect(self.db_path, check_same_thread=False)
        self._load_sqlite_vec()
        self._create_vector_table()

    def _load_sqlite_vec(self) -> None:
        if not hasattr(self.con, "enable_load_extension"):
            raise RuntimeError(
                "This SQLite connection does not support extension loading."
            )

        self.con.enable_load_extension(True)
        sqlite_vec.load(self.con)
        self.con.enable_load_extension(False)

    def _create_vector_table(self) -> None:
        create_table_sql = f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors
            USING vec0(
                memory_id INTEGER PRIMARY KEY,
                embedding float[{self.dimension}]
            )
            """
        self.con.execute(create_table_sql)
        self.con.commit()

    def save_vector(
        self,
        memory_id: int,
        embedding: Sequence[float],
    ) -> None:
        if len(embedding) != self.dimension:
            raise ValueError(
                f"Expected embedding dimension {self.dimension}, got {len(embedding)}."
            )

        try:
            # sqlite-vec does not support REPLACE, so both statements must share
            # one local transaction to preserve the previous vector on failure.
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
        except Exception:
            self.con.rollback()
            raise

    def search_similar(
        self,
        query_embedding: Sequence[float],
        top_k: int = 3,
    ) -> list[VectorSearchResult]:
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

        return [VectorSearchResult(memory_id=row[0], distance=row[1]) for row in rows]

    def delete_vector(self, memory_id: int) -> None:
        """Delete a vector by memory_id."""
        try:
            self.con.execute(
                "DELETE FROM memory_vectors WHERE memory_id = ?",
                (memory_id,),
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    def has_vector(self, memory_id: int) -> bool:
        """Return whether a derived vector exists for one memory ID."""

        row = self.con.execute(
            "SELECT 1 FROM memory_vectors WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        return row is not None

    def list_memory_ids(self) -> set[int]:
        """Return every memory ID currently present in the vector index."""

        rows = self.con.execute("SELECT memory_id FROM memory_vectors").fetchall()
        return {row[0] for row in rows}

    def close(self) -> None:
        self.con.close()
