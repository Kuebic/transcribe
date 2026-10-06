import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import FakeTranscriber
from helpers import list_rows, recording_path, status_on_page, text_of, upload, wav_bytes
from transcribe.app import create_app
from transcribe.jobs import process_next_job

TRANSCRIBING_WITH_ELAPSED = r"Transcribing for \d+:\d{2}"


class ProcessKilled(BaseException):
    """Stands in for the container dying mid-Job: escapes the Job's own error handling."""


def wait_for_status(client: TestClient, path: str, status: str, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while (current := status_on_page(client.get(path).text)) != status:
        assert time.monotonic() < deadline, f"{path} still {current!r} after {seconds}s"
        time.sleep(0.02)


def status_cell(row: str) -> str:
    return re.search(r'<td class="status">(.*?)</td>', row, re.S).group(1)


def test_worker_thread_drains_the_queue_one_job_at_a_time(data_dir):
    in_flight = threading.Semaphore(1)
    overlapped = threading.Event()
    transcriber = FakeTranscriber()

    def one_at_a_time():
        if not in_flight.acquire(blocking=False):
            overlapped.set()
            return
        time.sleep(0.05)
        in_flight.release()

    transcriber.during = one_at_a_time

    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)) as client:
        first = recording_path(upload(client, "first.wav", wav_bytes(1)))
        second = recording_path(upload(client, "second.wav", wav_bytes(2)))

        wait_for_status(client, first, "Done")
        wait_for_status(client, second, "Done")

    assert len(transcriber.calls) == 2
    assert not overlapped.is_set()


def test_worker_takes_jobs_queued_before_it_started_in_upload_order(data_dir, transcriber):
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber, start_worker=False)) as client:
        first = recording_path(upload(client, "first.wav", wav_bytes(1)))
        second = recording_path(upload(client, "second.wav", wav_bytes(2)))

    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)) as client:
        wait_for_status(client, first, "Done")
        wait_for_status(client, second, "Done")

    sizes = [audio_path.stat().st_size for audio_path, _ in transcriber.calls]
    assert sizes == [len(wav_bytes(1)), len(wav_bytes(2))]


def test_job_left_transcribing_by_a_dead_process_is_queued_again_on_startup(data_dir, transcriber):
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber, start_worker=False)) as client:
        path = recording_path(upload(client, "lecture.wav", wav_bytes(1)))
        transcriber.error = ProcessKilled()
        with pytest.raises(ProcessKilled):
            process_next_job(data_dir, transcriber)
        assert status_on_page(client.get(path).text).startswith("Transcribing")

    transcriber.error = None
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber, start_worker=False)) as client:
        page = client.get(path).text
        assert status_on_page(page) == "Queued"
        assert "Started</dt>" not in page

        process_next_job(data_dir, transcriber)

        assert status_on_page(client.get(path).text) == "Done"


def test_status_cells_poll_while_the_job_is_queued(client):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))

    [row] = list_rows(client)
    assert f'hx-get="{path}/status"' in status_cell(row)
    assert 'hx-trigger="every' in status_cell(row)

    page = client.get(path).text
    assert re.search(rf'<dd class="status">.*hx-get="{path}/status\?reload=1".*</dd>', page, re.S)


def test_status_partial_reports_the_job_and_keeps_polling_while_queued(client):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))

    response = client.get(f"{path}/status")

    assert response.status_code == 200
    assert "Queued" in response.text
    assert 'hx-trigger="every' in response.text
    assert "HX-Refresh" not in response.headers


def test_status_stops_polling_once_the_job_is_done(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))

    process_next_job(data_dir, transcriber)

    partial = client.get(f"{path}/status").text
    assert "Done" in partial
    assert "hx-trigger" not in partial
    [row] = list_rows(client)
    assert "hx-trigger" not in status_cell(row)
    assert "hx-trigger" not in client.get(path).text


def test_status_stops_polling_once_the_job_has_failed(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))
    transcriber.error = RuntimeError("decoder exploded")

    process_next_job(data_dir, transcriber)

    assert "hx-trigger" not in client.get(f"{path}/status").text


def test_recording_page_reloads_when_its_job_finishes(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))
    assert "HX-Refresh" not in client.get(f"{path}/status?reload=1").headers

    process_next_job(data_dir, transcriber)

    assert client.get(f"{path}/status?reload=1").headers["HX-Refresh"] == "true"
    assert "HX-Refresh" not in client.get(f"{path}/status").headers


def test_transcribing_status_shows_elapsed_time(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))
    seen = {}

    def look():
        seen["page"] = client.get(path).text
        seen["row"] = list_rows(client)[0]
        seen["partial"] = client.get(f"{path}/status").text

    transcriber.during = look
    process_next_job(data_dir, transcriber)

    assert re.fullmatch(TRANSCRIBING_WITH_ELAPSED, status_on_page(seen["page"]))
    assert re.fullmatch(TRANSCRIBING_WITH_ELAPSED, text_of(status_cell(seen["row"])))
    assert re.fullmatch(TRANSCRIBING_WITH_ELAPSED, text_of(seen["partial"]))
    assert 'hx-trigger="every' in seen["partial"]


def test_status_of_unknown_recording_is_not_found(client):
    assert client.get("/recordings/9999/status").status_code == 404


def test_pages_load_htmx_from_the_app_itself(client):
    page = client.get("/").text
    src = re.search(r'<script src="(/static/htmx[^"]*\.js)"', page).group(1)

    response = client.get(src)

    assert response.status_code == 200
    assert "htmx" in response.text
