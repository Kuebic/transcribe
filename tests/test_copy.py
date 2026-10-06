import re

from helpers import recording_path, upload, wav_bytes
from transcribe.jobs import process_next_job
from transcribe.transcriber import Segment

SEGMENTS = [
    Segment(start=0.0, end=3.0, text=" Hallo, hier ist Anna."),
    Segment(start=3.0, end=5.0, text=" Rufst du zurück?"),
    Segment(start=9.0, end=10.0, text=" Tschüss."),
]


def done_recording(client, data_dir, transcriber) -> str:
    transcriber.segments = SEGMENTS
    path = recording_path(upload(client, "anruf.m4a", wav_bytes(1), kind="call"))
    process_next_job(data_dir, transcriber)
    return path


def copy_buttons(page: str) -> dict[str, str]:
    return dict(re.findall(r'<button[^>]*class="copy"[^>]*data-src="([^"]+)"[^>]*>([^<]*)<', page))


def test_plain_transcript_is_served_as_text(client, data_dir, transcriber):
    path = done_recording(client, data_dir, transcriber)

    response = client.get(f"{path}/transcript.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "Hallo, hier ist Anna. Rufst du zurück?\n\nTschüss.\n"


def test_timestamped_transcript_is_served_as_text(client, data_dir, transcriber):
    path = done_recording(client, data_dir, transcriber)

    response = client.get(f"{path}/transcript.timestamped.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "[00:00] Hallo, hier ist Anna.\n[00:03] Rufst du zurück?\n[00:09] Tschüss.\n"


def test_transcript_text_is_not_found_before_the_job_is_done(client):
    path = recording_path(upload(client, "anruf.m4a", wav_bytes(1)))

    assert client.get(f"{path}/transcript.txt").status_code == 404
    assert client.get(f"{path}/transcript.timestamped.txt").status_code == 404


def test_transcript_text_is_not_found_for_an_unknown_recording(client):
    assert client.get("/recordings/999/transcript.txt").status_code == 404
    assert client.get("/recordings/999/transcript.timestamped.txt").status_code == 404


def test_done_recording_page_has_both_copy_buttons(client, data_dir, transcriber):
    path = done_recording(client, data_dir, transcriber)

    page = client.get(path).text

    assert copy_buttons(page) == {
        f"{path}/transcript.txt": "Copy",
        f"{path}/transcript.timestamped.txt": "Copy with timestamps",
    }
    assert '<script src="/static/copy.js" defer></script>' in page
    assert client.get("/static/copy.js").status_code == 200


def test_copy_buttons_are_absent_until_the_job_is_done(client, data_dir, transcriber):
    queued = recording_path(upload(client, "queued.m4a", wav_bytes(1)))
    assert copy_buttons(client.get(queued).text) == {}

    transcriber.error = RuntimeError("decoder exploded")
    process_next_job(data_dir, transcriber)

    assert copy_buttons(client.get(queued).text) == {}
