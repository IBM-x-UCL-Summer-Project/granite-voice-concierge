CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    content       TEXT NOT NULL,
    layer         TEXT NOT NULL,
    memory_key    TEXT,
    revision      INTEGER NOT NULL DEFAULT 1,
    indexed_revision INTEGER NOT NULL DEFAULT 0,
    deleted_at    INTEGER,

    created_at    INTEGER NOT NULL,
    event_time    INTEGER,

    last_accessed INTEGER,                
    strength      INTEGER NOT NULL DEFAULT 1,

    person        TEXT,
    source_type   TEXT,
    topic         TEXT
);
