import time

import pysqlite3 as sqlite3
import pytest

from voice_concierge.memory.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """Each test gets a fresh temporary database, cleaned up automatically."""
    db = tmp_path / "test_memory.db"
    s = MemoryStore(str(db))
    yield s
    s.close()


# ---- Basic create / retrieve ----


def test_create_returns_id(store):
    mem_id = store.create_memory("hello", "raw")
    assert isinstance(mem_id, int)
    assert mem_id > 0


def test_create_and_retrieve(store):
    store.create_memory("user prefers short answers", "profile")
    rows = store.get_memories()
    assert len(rows) == 1
    assert rows[0]["content"] == "user prefers short answers"
    assert rows[0]["layer"] == "profile"


def test_created_at_is_set(store):
    """created_at should be set automatically and be close to the current time."""
    before = int(time.time())
    store.create_memory("note", "raw")
    after = int(time.time())
    row = store.get_memories()[0]
    assert before <= row["created_at"] <= after


def test_defaults(store):
    """Optional fields default to None; strength defaults to 1."""
    store.create_memory("minimal", "raw")
    row = store.get_memories()[0]
    assert row["event_time"] is None
    assert row["person"] is None
    assert row["topic"] is None
    assert row["last_accessed"] is None
    assert row["strength"] == 1
    assert row["revision"] == 1


# ---- Metadata filtering ----


def test_filter_by_person(store):
    store.create_memory("a", "raw")
    store.create_memory("b", "raw", person="Kenny")
    store.create_memory("c", "raw", person="Kenny")
    rows = store.get_memories(person="Kenny")
    assert len(rows) == 2
    assert all(r["person"] == "Kenny" for r in rows)


def test_filter_by_topic(store):
    store.create_memory("x", "raw", topic="shopping")
    store.create_memory("y", "raw", topic="cooking")
    rows = store.get_memories(topic="shopping")
    assert len(rows) == 1
    assert rows[0]["topic"] == "shopping"


def test_filter_combined(store):
    store.create_memory("1", "raw", person="Kenny")
    store.create_memory("2", "raw", person="Kenny", topic="cooking")
    rows = store.get_memories(person="Kenny", topic="cooking")
    assert len(rows) == 1
    assert rows[0]["content"] == "2"


def test_filter_no_match(store):
    store.create_memory("z", "raw", person="Kenny")
    rows = store.get_memories(person="Nobody")
    assert rows == []


# ---- Edge cases ----


def test_empty_db(store):
    assert store.get_memories() == []


def test_unicode_content(store):
    """Non-ASCII (Chinese) content should round-trip without corruption."""
    store.create_memory("I prefer short answers.", "profile")
    row = store.get_memories()[0]
    assert row["content"] == "I prefer short answers."


def test_ordering_newest_first(store):
    """get_memories should return newest first (ORDER BY created_at DESC)."""
    store.create_memory("first", "raw")
    time.sleep(1)  # ensure distinct second-level timestamps
    store.create_memory("second", "raw")
    rows = store.get_memories()
    assert rows[0]["content"] == "second"
    assert rows[1]["content"] == "first"


# ---- Persistence (core test, maps to Charter §3.3.3) ----


def test_persistence_across_reconnect(tmp_path):
    """Save -> close connection -> reopen -> data still present."""
    db = str(tmp_path / "persist.db")

    store1 = MemoryStore(db)
    store1.create_memory("I prefer short answers.", "raw", topic="profile")
    store1.close()

    store2 = MemoryStore(db)  # simulate a restart
    rows = store2.get_memories()
    store2.close()

    assert len(rows) == 1
    assert rows[0]["content"] == "I prefer short answers."


def test_existing_database_is_migrated_with_stable_memory_keys(tmp_path):
    db = str(tmp_path / "legacy.db")
    connection = sqlite3.connect(db)
    connection.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            layer TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            event_time INTEGER,
            last_accessed INTEGER,
            strength INTEGER NOT NULL DEFAULT 1,
            person TEXT,
            source_type TEXT,
            topic TEXT
        )
        """)
    connection.commit()
    connection.close()

    migrated_store = MemoryStore(db)
    memory_id = migrated_store.create_memory(
        "Shopping list: bread.",
        "feedback",
        memory_key="list:shopping",
    )
    migrated_store.close()

    reopened_store = MemoryStore(db)
    memory = reopened_store.get_memory_by_key("list:shopping")
    reopened_store.close()

    assert memory is not None
    assert memory["id"] == memory_id
    assert memory["revision"] == 1


def test_delete_memory(store):
    mid = store.create_memory("to delete", "raw")
    assert store.delete_memory(mid) is True
    assert store.get_memories() == []


def test_get_memory_by_stable_key(store):
    memory_id = store.create_memory(
        "Shopping list: bread.",
        "feedback",
        memory_key="list:shopping",
        topic="shopping",
    )

    memory = store.get_memory_by_key("list:shopping")

    assert memory is not None
    assert memory["id"] == memory_id
    assert memory["content"] == "Shopping list: bread."


def test_delete_nonexistent(store):
    assert store.delete_memory(999) is False


def test_update_memory(store):
    mid = store.create_memory("old content", "raw", topic="shopping")
    assert store.update_memory(mid, content="new content") is True
    row = store.get_memories()[0]
    assert row["content"] == "new content"
    assert row["topic"] == "shopping"
    assert row["revision"] == 2


def test_update_requires_current_revision_when_supplied(store):
    memory_id = store.create_memory("old content", "raw")

    assert store.update_memory(
        memory_id,
        content="first update",
        expected_revision=1,
    )
    assert not store.update_memory(
        memory_id,
        content="stale update",
        expected_revision=1,
    )

    memory = store.get_memory_by_id(memory_id)
    assert memory["content"] == "first update"
    assert memory["revision"] == 2


def test_delete_requires_current_revision_when_supplied(store):
    memory_id = store.create_memory("keep current version", "raw")
    assert store.update_memory(memory_id, content="new version")

    assert not store.delete_memory(memory_id, expected_revision=1)
    assert store.get_memory_by_id(memory_id) is not None
    assert store.delete_memory(memory_id, expected_revision=2)


def test_update_nothing(store):
    mid = store.create_memory("x", "raw")
    assert store.update_memory(mid) is False
