"""Storing a Recording's audio and reading/writing Recordings, Kinds and their Jobs."""

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO

ACCEPTED_EXTENSIONS = ("m4a", "mp3", "ogg", "opus", "wav", "flac", "aac", "webm")

CHUNK_BYTES = 1024 * 1024


def audio_extension(filename: str) -> str | None:
    """The lower-cased extension if it is an accepted audio format, else None."""
    extension = PurePath(filename).suffix.lstrip(".").lower()
    return extension if extension in ACCEPTED_EXTENSIONS else None


def title_from_filename(filename: str) -> str:
    return PurePath(filename).stem


@dataclass(frozen=True)
class StagedAudio:
    """Audio written to the data directory's temp area, named only by its content hash so far."""

    path: Path
    content_hash: str

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


def stage_audio(source: BinaryIO, data_dir: Path) -> StagedAudio:
    """Copy the source to a temp file under the data directory while hashing it."""
    tmp_dir = data_dir / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    digest = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False)
    try:
        with tmp:
            while chunk := source.read(CHUNK_BYTES):
                digest.update(chunk)
                tmp.write(chunk)
    except BaseException:
        Path(tmp.name).unlink(missing_ok=True)
        raise
    return StagedAudio(path=Path(tmp.name), content_hash=digest.hexdigest())


def keep_audio(staged: StagedAudio, data_dir: Path, extension: str) -> str:
    """Move staged audio to its permanent name; returns the path relative to the data directory."""
    relative = f"audio/{staged.content_hash}.{extension}"
    os.replace(staged.path, data_dir / relative)
    return relative


def list_kinds(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, name FROM kinds ORDER BY id").fetchall()


def kind_exists(conn: sqlite3.Connection, kind_id: int) -> bool:
    return conn.execute("SELECT 1 FROM kinds WHERE id = ?", (kind_id,)).fetchone() is not None


def find_recording_by_hash(conn: sqlite3.Connection, content_hash: str) -> int | None:
    row = conn.execute("SELECT id FROM recordings WHERE content_hash = ?", (content_hash,)).fetchone()
    return row["id"] if row else None


def create_recording(
    conn: sqlite3.Connection,
    *,
    title: str,
    kind_id: int,
    original_filename: str,
    content_hash: str,
    audio_path: str,
    duration_seconds: float | None,
    language_requested: str | None,
) -> int:
    """Insert a Recording together with its Queued Job."""
    with conn:
        recording_id = conn.execute(
            """
            INSERT INTO recordings
                (title, kind_id, original_filename, content_hash, audio_path,
                 duration_seconds, language_requested)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, kind_id, original_filename, content_hash, audio_path,
             duration_seconds, language_requested),
        ).lastrowid
        conn.execute("INSERT INTO jobs (recording_id) VALUES (?)", (recording_id,))
    return recording_id


RECORDING_SELECT = """
SELECT
    r.id, r.title, r.original_filename, r.duration_seconds, r.language_requested,
    r.language_detected, r.model_name, r.created_at, k.name AS kind_name, j.status
FROM recordings r
JOIN kinds k ON k.id = r.kind_id
LEFT JOIN jobs j ON j.id = (SELECT MAX(id) FROM jobs WHERE recording_id = r.id)
"""


def list_recordings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All Recordings newest first, each with its Kind name and latest Job status."""
    return conn.execute(
        f"{RECORDING_SELECT} ORDER BY r.created_at DESC, r.id DESC"
    ).fetchall()


def get_recording(conn: sqlite3.Connection, recording_id: int) -> sqlite3.Row | None:
    return conn.execute(f"{RECORDING_SELECT} WHERE r.id = ?", (recording_id,)).fetchone()
