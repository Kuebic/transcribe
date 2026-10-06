import re

import pytest

from helpers import recording_path, upload, wav_bytes
from transcribe.jobs import process_next_job
from transcribe.transcriber import Segment

AUDIO = wav_bytes(1)


def player_src(page: str) -> str | None:
    match = re.search(r'<audio[^>]*\bsrc="([^"]+)"', page)
    return match.group(1) if match else None


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("anruf.m4a", "audio/mp4"), ("lecture.mp3", "audio/mpeg"), ("memo.opus", "audio/ogg")],
)
def test_audio_is_served_whole_with_its_content_type(client, filename, content_type):
    path = recording_path(upload(client, filename, AUDIO))

    response = client.get(f"{path}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == AUDIO


def test_audio_range_request_returns_only_that_range(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))

    response = client.get(f"{path}/audio", headers={"Range": "bytes=100-199"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{len(AUDIO)}"
    assert response.headers["content-type"] == "audio/mp4"
    assert response.content == AUDIO[100:200]


def test_audio_open_ended_range_runs_to_the_end_of_the_file(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))

    response = client.get(f"{path}/audio", headers={"Range": "bytes=16000-"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 16000-{len(AUDIO) - 1}/{len(AUDIO)}"
    assert response.content == AUDIO[16000:]


def test_audio_is_not_found_for_an_unknown_recording(client):
    assert client.get("/recordings/999/audio").status_code == 404


def test_audio_is_not_found_once_the_recording_has_no_audio(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    client.post(f"{path}/delete-audio")

    assert client.get(f"{path}/audio").status_code == 404


def test_recording_page_has_a_player_for_its_audio(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))

    page = client.get(path).text

    assert player_src(page) == f"{path}/audio"
    assert '<script src="/static/playback.js" defer></script>' in page
    assert client.get("/static/playback.js").status_code == 200


def test_recording_page_has_no_player_without_audio(client, data_dir, transcriber):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    process_next_job(data_dir, transcriber)
    client.post(f"{path}/delete-audio")

    page = client.get(path).text

    assert "<audio" not in page
    assert "playback.js" not in page
    assert "Hello there." in page


def test_segments_carry_their_start_and_end_for_seeking(client, data_dir, transcriber):
    transcriber.segments = [
        Segment(start=0.0, end=3.0, text=" Hallo."),
        Segment(start=3.5, end=7.25, text=" Tschüss."),
    ]
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    process_next_job(data_dir, transcriber)

    page = client.get(path).text

    assert re.findall(r'<li class="segment" data-start="([^"]+)" data-end="([^"]+)"', page) == [
        ("0.0", "3.0"),
        ("3.5", "7.25"),
    ]
