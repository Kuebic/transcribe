"""Draining the Job queue: one plain function the worker loops over and tests call directly."""

from pathlib import Path

from transcribe.db import DB_FILENAME, connect
from transcribe.transcriber import Transcriber

CLAIM_OLDEST_QUEUED = """
UPDATE jobs
SET status = 'transcribing', started_at = CURRENT_TIMESTAMP, attempts = attempts + 1
WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1)
RETURNING id, recording_id
"""


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


def process_next_job(data_dir: Path, transcriber: Transcriber) -> int | None:
    """Transcribe the oldest Queued Job's Recording; returns the Job id, or None when none is Queued."""
    data_dir = Path(data_dir)
    conn = connect(data_dir / DB_FILENAME)
    try:
        with conn:
            job = conn.execute(CLAIM_OLDEST_QUEUED).fetchone()
        if job is None:
            return None
        job_id, recording_id = job["id"], job["recording_id"]
        recording = conn.execute(
            "SELECT audio_path, language_requested FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()

        try:
            transcription = transcriber.transcribe(
                data_dir / recording["audio_path"], recording["language_requested"]
            )
        except Exception as error:
            with conn:
                conn.execute(
                    """
                    UPDATE jobs SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error = ?
                    WHERE id = ?
                    """,
                    (str(error) or type(error).__name__, job_id),
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
