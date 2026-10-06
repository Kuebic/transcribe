import hashlib
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from helpers import kind_id, list_rows, recording_path, upload, wav_bytes
from transcribe.app import create_app

ACCEPTED_EXTENSIONS = ["m4a", "mp3", "ogg", "opus", "wav", "flac", "aac", "webm"]


def test_upload_page_offers_seeded_kinds_title_and_language_defaulting_to_english(client):
    page = client.get("/upload")

    assert page.status_code == 200
    for name in ("call", "lecture", "talk", "note"):
        kind_id(client, name)
    assert 'name="title"' in page.text
    assert re.search(r'<option value="en" selected>', page.text)


def test_uploading_one_recording_redirects_to_its_page_showing_queued(client):
    response = upload(client, "Week 3.m4a", wav_bytes(1), title="Thermodynamics")

    page = client.get(recording_path(response))
    assert page.status_code == 200
    assert "Thermodynamics" in page.text
    assert "lecture" in page.text
    assert "Queued" in page.text


def test_blank_title_falls_back_to_filename_without_extension(client):
    response = upload(client, "Call with Anna 2026-10-01.opus", wav_bytes(1), title="  ")

    page = client.get(recording_path(response)).text
    assert "Call with Anna 2026-10-01" in page
    assert "Call with Anna 2026-10-01.opus</h1>" not in page


def test_chosen_language_is_shown_on_the_recording_page(client):
    response = upload(client, "vortrag.mp3", wav_bytes(1), language="de")

    assert "de" in re.search(r"Language.*?</dd>", client.get(recording_path(response)).text, re.S).group(0)


def test_automatic_language_detection_is_kept_rather_than_defaulting_to_english(client):
    response = upload(client, "unknown.mp3", wav_bytes(1), language="auto")

    language = re.search(r"Language</dt>\s*<dd>(.*?)</dd>", client.get(recording_path(response)).text).group(1)
    assert language == "Detect automatically"


@pytest.mark.parametrize("extension", ACCEPTED_EXTENSIONS + ["M4A"])
def test_common_audio_formats_are_accepted(client, extension):
    response = upload(client, f"clip.{extension}", f"{extension} content".encode())

    assert client.get(recording_path(response)).status_code == 200


@pytest.mark.parametrize("filename", ["notes.txt", "video.mp4", "no-extension"])
def test_other_formats_are_rejected_with_a_clear_message(client, filename):
    response = upload(client, filename, b"not audio")

    assert response.status_code == 400
    assert "m4a, mp3, ogg, opus, wav, flac, aac, webm" in response.text
    assert list_rows(client) == []


def test_unknown_kind_is_rejected(client):
    response = client.post(
        "/upload",
        data={"kind_id": "9999"},
        files={"files": ("clip.wav", wav_bytes(1), "audio/wav")},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert list_rows(client) == []


def test_body_over_the_limit_is_rejected(data_dir, transcriber):
    with TestClient(create_app(data_dir, transcriber, max_upload_bytes=4096)) as client:
        response = upload(client, "long.wav", b"\x00" * 8192)

        assert response.status_code == 413
        assert "too large" in response.text.lower()
        assert list_rows(client) == []
    assert list((data_dir / "audio").iterdir()) == []


def test_streamed_body_over_the_limit_is_rejected_without_a_content_length(data_dir, transcriber):
    boundary = "recording-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="kind_id"\r\n\r\n1\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="long.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + b"\x00" * 8192 + f"\r\n--{boundary}--\r\n".encode()

    def chunks():
        for i in range(0, len(body), 1024):
            yield body[i : i + 1024]

    with TestClient(create_app(data_dir, transcriber, max_upload_bytes=4096)) as client:
        response = client.post(
            "/upload",
            content=chunks(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
            follow_redirects=False,
        )

        assert response.status_code == 413
        assert list_rows(client) == []


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_duration_is_listed_before_transcription_runs(client):
    upload(client, "short.wav", wav_bytes(75))

    [row] = list_rows(client)
    assert "1:15" in row
    assert "Queued" in row


def test_list_shows_newest_first_with_title_kind_duration_date_and_status(client):
    upload(client, "first.wav", wav_bytes(1), kind="call")
    upload(client, "second.wav", wav_bytes(2), kind="lecture")

    first_row, second_row = list_rows(client)
    assert "second" in first_row and "lecture" in first_row
    assert "first" in second_row and "call" in second_row
    for row in (first_row, second_row):
        assert re.search(r"\d{4}-\d{2}-\d{2}", row)
        assert "Queued" in row
        assert re.search(r'class="duration"', row)


def test_audio_is_stored_by_content_hash_and_original_filename_is_not_on_disk(client, data_dir):
    content = wav_bytes(1)
    upload(client, "Private Call With Bob.m4a", content)

    stored = [p.name for p in (data_dir / "audio").iterdir()]
    assert stored == [hashlib.sha256(content).hexdigest() + ".m4a"]
    assert not [p for p in data_dir.rglob("*") if "Bob" in p.name]


def test_reupload_of_identical_content_opens_the_existing_recording(client):
    content = wav_bytes(1)
    first = recording_path(upload(client, "original.wav", content))

    second = recording_path(upload(client, "renamed.wav", content))

    assert second == first
    assert len(list_rows(client)) == 1


def test_unknown_recording_is_not_found(client):
    assert client.get("/recordings/9999").status_code == 404


def test_empty_list_points_to_the_upload_page(client):
    page = client.get("/")

    assert page.status_code == 200
    assert 'href="/upload"' in page.text


def test_home_page_lists_uploaded_recording_with_link(client):
    path = recording_path(upload(client, "Seminar.flac", wav_bytes(1)))

    [row] = list_rows(client)
    assert f'href="{path}"' in row
    assert "Seminar" in row
