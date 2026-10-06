import sqlite3
from pathlib import Path

DB_FILENAME = "transcribe.sqlite3"

SCHEMA_VERSION = 1

SEED_KINDS = ("call", "lecture", "talk", "note")

SCHEMA = """
CREATE TABLE kinds (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE recordings (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    kind_id INTEGER NOT NULL REFERENCES kinds(id),
    original_filename TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    audio_path TEXT,
    duration_seconds REAL,
    language_requested TEXT,
    language_detected TEXT,
    model_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE segments (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    "index" INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (recording_id, "index")
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'transcribing', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before TEXT,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            with conn:
                conn.executescript(SCHEMA)
                conn.executemany(
                    "INSERT INTO kinds (name) VALUES (?)",
                    [(name,) for name in SEED_KINDS],
                )
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()
