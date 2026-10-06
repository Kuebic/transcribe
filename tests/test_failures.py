import re
import time
from datetime import UTC, datetime, timedelta

import pytest

from helpers import list_rows, recording_path, status_on_page, text_of, upload, wav_bytes
from transcribe.db import DB_FILENAME, connect
from transcribe.jobs import process_next_job

# What Whisper reports when torch runs out of GPU memory (see whisper.failure_message).
OOM = RuntimeError("OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB")


def jobs_of(data_dir, path: str) -> list[dict]:
    recording_id = int(path.rsplit("/", 1)[1])
    conn = connect(data_dir / DB_FILENAME)
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE recording_id = ? ORDER BY id", (recording_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def retry_button(page: str) -> re.Match | None:
    return re.search(r'<form method="post" action="(/recordings/\d+/retry)">', page)


@pytest.mark.parametrize(
    "error",
    [
        OOM,
        RuntimeError("CUDA error: out of memory"),
        type("OutOfMemoryError", (RuntimeError,), {})("Tried to allocate 2.00 GiB"),
    ],
)
def test_out_of_memory_queues_the_job_again_after_a_wait(client, data_dir, transcriber, error):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    transcriber.error = error
    now = datetime.now(UTC).replace(microsecond=0)

    process_next_job(data_dir, transcriber, now=now)

    [job] = jobs_of(data_dir, path)
    assert job["status"] == "queued"
    assert job["attempts"] == 1
    assert utc(job["not_before"]) == now + timedelta(minutes=1)
    assert status_on_page(client.get(path).text) == (
        f"Queued, trying again after {job['not_before']} UTC: {error}"
    )


def test_wait_counts_from_when_the_gpu_ran_out_not_from_when_the_job_started(
    client, data_dir, transcriber
):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    transcriber.error = OOM
    transcriber.during = lambda: time.sleep(2)
    started = datetime.now(UTC).replace(microsecond=0)

    process_next_job(data_dir, transcriber)

    [job] = jobs_of(data_dir, path)
    assert utc(job["not_before"]) >= started + timedelta(minutes=1, seconds=2)


def test_waiting_job_is_skipped_until_its_time_has_come(client, data_dir, transcriber):
    waiting = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    later = recording_path(upload(client, "later.wav", wav_bytes(2)))
    transcriber.error = OOM
    now = datetime.now(UTC)
    process_next_job(data_dir, transcriber, now=now)
    transcriber.error = None

    process_next_job(data_dir, transcriber, now=now + timedelta(seconds=59))

    assert status_on_page(client.get(later).text) == "Done"
    assert status_on_page(client.get(waiting).text).startswith("Queued")
    assert process_next_job(data_dir, transcriber, now=now + timedelta(seconds=59)) is None

    process_next_job(data_dir, transcriber, now=now + timedelta(minutes=1))

    assert status_on_page(client.get(waiting).text) == "Done"


def test_waits_grow_and_the_fourth_out_of_memory_fails_the_job(client, data_dir, transcriber):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    transcriber.error = OOM
    now = datetime.now(UTC).replace(microsecond=0)

    waits = []
    for _ in range(3):
        process_next_job(data_dir, transcriber, now=now)
        [job] = jobs_of(data_dir, path)
        assert job["status"] == "queued"
        waits.append(utc(job["not_before"]) - now)
        now = utc(job["not_before"])

    assert waits == [timedelta(minutes=1), timedelta(minutes=4), timedelta(minutes=10)]

    process_next_job(data_dir, transcriber, now=now)

    [job] = jobs_of(data_dir, path)
    assert job["status"] == "failed"
    assert job["attempts"] == 4
    assert "CUDA out of memory" in job["error"]
    assert status_on_page(client.get(path).text).startswith("Failed")
    assert len(transcriber.calls) == 4


def test_other_errors_fail_the_job_at_once_with_the_error_shown(client, data_dir, transcriber):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    transcriber.error = RuntimeError("ffmpeg could not decode the audio")

    process_next_job(data_dir, transcriber)

    [job] = jobs_of(data_dir, path)
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["error"] == "ffmpeg could not decode the audio"
    assert status_on_page(client.get(path).text) == "Failed: ffmpeg could not decode the audio"
    [row] = list_rows(client)
    assert "Failed: ffmpeg could not decode the audio" in text_of(row)


def test_retry_queues_a_fresh_job_and_keeps_the_failed_one(client, data_dir, transcriber):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    transcriber.error = RuntimeError("decoder exploded")
    process_next_job(data_dir, transcriber)
    [failed] = jobs_of(data_dir, path)

    button = retry_button(client.get(path).text)
    assert button and button.group(1) == f"{path}/retry"
    response = client.post(f"{path}/retry", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == path
    page = client.get(path).text
    assert status_on_page(page) == "Queued"
    assert retry_button(page) is None
    old, new = jobs_of(data_dir, path)
    assert old == failed
    assert new["status"] == "queued"
    assert new["attempts"] == 0

    transcriber.error = None
    process_next_job(data_dir, transcriber)

    assert status_on_page(client.get(path).text) == "Done"
    assert jobs_of(data_dir, path)[0] == failed


def test_retry_does_nothing_while_a_job_is_queued_or_transcribing(client, data_dir, transcriber):
    path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
    assert retry_button(client.get(path).text) is None

    assert client.post(f"{path}/retry", follow_redirects=False).status_code == 303
    assert len(jobs_of(data_dir, path)) == 1

    transcriber.during = lambda: client.post(f"{path}/retry")
    process_next_job(data_dir, transcriber)

    [job] = jobs_of(data_dir, path)
    assert job["status"] == "done"
    client.post(f"{path}/retry")
    assert len(jobs_of(data_dir, path)) == 1


def test_retry_of_unknown_recording_is_not_found(client):
    assert client.post("/recordings/9999/retry").status_code == 404
