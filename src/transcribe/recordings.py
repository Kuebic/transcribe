"""Storing a Recording's audio and reading/writing Recordings, Kinds and their Jobs."""

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO

# The content type each accepted extension is served with; spelled out because Python's
# mimetypes table does not know all of them on every platform.
AUDIO_CONTENT_TYPES = {
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "webm": "audio/webm",
}

ACCEPTED_EXTENSIONS = tuple(AUDIO_CONTENT_TYPES)

CHUNK_BYTES = 1024 * 1024


def audio_extension(filename: str) -> str | None:
    """The lower-cased extension if it is an accepted audio format, else None."""
    extension = PurePath(filename).suffix.lstrip(".").lower()
    return extension if extension in ACCEPTED_EXTENSIONS else None


def audio_content_type(audio_path: str) -> str:
    """The content type to serve a kept audio file with; its extension was accepted at upload."""
    return AUDIO_CONTENT_TYPES[audio_extension(audio_path)]


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


def list_kinds_with_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every Kind with how many Recordings have it."""
    return conn.execute(
        """
        SELECT k.id, k.name, COUNT(r.id) AS recording_count
        FROM kinds k LEFT JOIN recordings r ON r.kind_id = k.id
        GROUP BY k.id ORDER BY k.id
        """
    ).fetchall()


def get_kind(conn: sqlite3.Connection, kind_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT id, name FROM kinds WHERE id = ?", (kind_id,)).fetchone()


def kind_exists(conn: sqlite3.Connection, kind_id: int) -> bool:
    return get_kind(conn, kind_id) is not None


def kind_name_taken(conn: sqlite3.Connection, name: str, *, other_than: int | None = None) -> bool:
    """Whether another Kind already has this name, ignoring case."""
    row = conn.execute(
        "SELECT 1 FROM kinds WHERE name = ? COLLATE NOCASE AND id IS NOT ?", (name, other_than)
    ).fetchone()
    return row is not None


def add_kind(conn: sqlite3.Connection, name: str) -> int:
    with conn:
        return conn.execute("INSERT INTO kinds (name) VALUES (?)", (name,)).lastrowid


def rename_kind(conn: sqlite3.Connection, kind_id: int, name: str) -> None:
    with conn:
        conn.execute("UPDATE kinds SET name = ? WHERE id = ?", (name, kind_id))


def delete_kind(conn: sqlite3.Connection, kind_id: int) -> bool:
    """Remove the Kind unless a Recording has it; returns whether it was removed."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM kinds WHERE id = ? AND NOT EXISTS (SELECT 1 FROM recordings WHERE kind_id = ?)",
            (kind_id, kind_id),
        )
    return cursor.rowcount == 1


def count_recordings_of_kind(conn: sqlite3.Connection, kind_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM recordings WHERE kind_id = ?", (kind_id,)).fetchone()[0]


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
    r.id, r.title, r.original_filename, r.audio_path, r.duration_seconds, r.language_requested,
    r.language_detected, r.model_name, r.created_at, r.kind_id, k.name AS kind_name,
    j.status, j.started_at, j.finished_at, j.not_before, j.error,
    CASE WHEN j.status = 'transcribing'
        THEN strftime('%s', 'now') - strftime('%s', j.started_at)
    END AS running_seconds
FROM recordings r
JOIN kinds k ON k.id = r.kind_id
LEFT JOIN jobs j ON j.id = (SELECT MAX(id) FROM jobs WHERE recording_id = r.id)
"""


def list_recordings(conn: sqlite3.Connection, *, kind_id: int | None = None) -> list[sqlite3.Row]:
    """Recordings newest first, each with its Kind name and latest Job status; all Kinds unless one is given."""
    return conn.execute(
        f"{RECORDING_SELECT} WHERE ? IS NULL OR r.kind_id = ? ORDER BY r.created_at DESC, r.id DESC",
        (kind_id, kind_id),
    ).fetchall()


def get_recording(conn: sqlite3.Connection, recording_id: int) -> sqlite3.Row | None:
    return conn.execute(f"{RECORDING_SELECT} WHERE r.id = ?", (recording_id,)).fetchone()


def list_segments(conn: sqlite3.Connection, recording_id: int) -> list[sqlite3.Row]:
    """The Recording's Transcript in order; empty until its Job is Done."""
    return conn.execute(
        'SELECT start_seconds, end_seconds, text FROM segments WHERE recording_id = ? ORDER BY "index"',
        (recording_id,),
    ).fetchall()


def retry_recording(conn: sqlite3.Connection, recording_id: int) -> bool:
    """Queue a fresh Job if the Recording's latest Job Failed; earlier Jobs stay as history.

    Returns whether a Job was queued; never while another Job of the Recording is still live.
    """
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs (recording_id)
            SELECT ? WHERE (
                SELECT status FROM jobs WHERE recording_id = ? ORDER BY id DESC LIMIT 1
            ) = 'failed'
            """,
            (recording_id, recording_id),
        )
    return cursor.rowcount == 1


def update_recording(
    conn: sqlite3.Connection, recording_id: int, *, title: str | None = None, kind_id: int | None = None
) -> None:
    """Change the title and/or Kind; a field left as None keeps its value."""
    with conn:
        conn.execute(
            "UPDATE recordings SET title = COALESCE(?, title), kind_id = COALESCE(?, kind_id) WHERE id = ?",
            (title, kind_id, recording_id),
        )


def _remove_audio(conn: sqlite3.Connection, data_dir: Path, recording_id: int, statement: str) -> None:
    """Run the statement on the Recording, then remove the audio file it had."""
    with conn:
        row = conn.execute("SELECT audio_path FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        conn.execute(statement, (recording_id,))
    if row and row["audio_path"]:
        (data_dir / row["audio_path"]).unlink(missing_ok=True)


def delete_audio(conn: sqlite3.Connection, data_dir: Path, recording_id: int) -> None:
    """Remove the Recording's audio file; the Recording and its Transcript stay."""
    _remove_audio(conn, data_dir, recording_id, "UPDATE recordings SET audio_path = NULL WHERE id = ?")


def delete_recording(conn: sqlite3.Connection, data_dir: Path, recording_id: int) -> None:
    """Remove the Recording with its audio file; its Segments and Jobs go with it by cascade."""
    _remove_audio(conn, data_dir, recording_id, "DELETE FROM recordings WHERE id = ?")
