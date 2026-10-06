"""Draining the Job queue: plain functions the app and worker call and tests call directly."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from transcribe.db import DB_FILENAME, connect
from transcribe.transcriber import Transcriber

# How long a Job waits before its next attempt after the GPU ran out of memory on attempt 1, 2, 3.
OUT_OF_MEMORY_WAITS = (timedelta(minutes=1), timedelta(minutes=4), timedelta(minutes=10))

MAX_ATTEMPTS = len(OUT_OF_MEMORY_WAITS) + 1

CLAIM_OLDEST_DUE = """
UPDATE jobs
SET status = 'transcribing', started_at = CURRENT_TIMESTAMP, attempts = attempts + 1,
    not_before = NULL, error = NULL
WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'queued' AND (not_before IS NULL OR not_before <= ?)
    ORDER BY id LIMIT 1
)
RETURNING id, recording_id, attempts
"""


def sqlite_time(moment: datetime) -> str:
    """The UTC form CURRENT_TIMESTAMP uses, so stored times compare as text."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def is_out_of_memory(error: Exception) -> bool:
    """Whether the error looks like CUDA running out of memory, which can pass once the GPU frees up."""
    text = f"{type(error).__name__}: {error}".lower()
    return "out of memory" in text or "outofmemoryerror" in text


def requeue_interrupted_jobs(data_dir: Path) -> None:
    """Put Jobs a previous process left Transcribing back in the queue to start over."""
    conn = connect(Path(data_dir) / DB_FILENAME)
    try:
        with conn:
            conn.execute(
                "UPDATE jobs SET status = 'queued', started_at = NULL WHERE status = 'transcribing'"
            )
    finally:
        conn.close()


def process_next_job(
    data_dir: Path, transcriber: Transcriber, *, now: datetime | None = None
) -> int | None:
    """Transcribe the oldest Queued Job's Recording that is due; returns the Job id, or None.

    Running out of GPU memory queues the Job again after a growing wait, counted from the
    failure; any other error, or running out on the last attempt, fails it. Tests pin the clock
    with now.
    """
    data_dir = Path(data_dir)
    conn = connect(data_dir / DB_FILENAME)
    try:
        with conn:
            job = conn.execute(
                CLAIM_OLDEST_DUE, (sqlite_time(now or datetime.now(UTC)),)
            ).fetchone()
        if job is None:
            return None
        job_id, recording_id, attempts = job["id"], job["recording_id"], job["attempts"]
        recording = conn.execute(
            "SELECT audio_path, language_requested FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()

        try:
            transcription = transcriber.transcribe(
                data_dir / recording["audio_path"], recording["language_requested"]
            )
        except Exception as error:
            message = str(error) or type(error).__name__
            if is_out_of_memory(error) and attempts < MAX_ATTEMPTS:
                not_before = (now or datetime.now(UTC)) + OUT_OF_MEMORY_WAITS[attempts - 1]
                with conn:
                    conn.execute(
                        """
                        UPDATE jobs SET status = 'queued', started_at = NULL, not_before = ?, error = ?
                        WHERE id = ?
                        """,
                        (sqlite_time(not_before), message, job_id),
                    )
                return job_id
            with conn:
                conn.execute(
                    """
                    UPDATE jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error = ?
                    WHERE id = ?
                    """,
                    (message, job_id),
                )
            return job_id

        with conn:
            conn.execute("DELETE FROM segments WHERE recording_id = ?", (recording_id,))
            conn.executemany(
                """
                INSERT INTO segments (recording_id, "index", start_seconds, end_seconds, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (recording_id, index, segment.start, segment.end, segment.text.strip())
                    for index, segment in enumerate(transcription.segments)
                ],
            )
            conn.execute(
                "UPDATE recordings SET language_detected = ?, model_name = ? WHERE id = ?",
                (transcription.language, transcription.model, recording_id),
            )
            conn.execute(
                "UPDATE jobs SET status = 'done', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
        return job_id
    finally:
        conn.close()
