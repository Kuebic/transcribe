import re

from helpers import kind_id, list_rows, recording_path, status_on_page, upload, wav_bytes
from transcribe.jobs import process_next_job

AUDIO = wav_bytes(1)


def audio_files(data_dir) -> list[str]:
    return sorted(p.name for p in (data_dir / "audio").iterdir())


def form_actions(page: str) -> list[str]:
    return re.findall(r'<form[^>]*\baction="([^"]+)"', page)


def transcribed(client, data_dir, transcriber, filename="anruf.m4a") -> str:
    path = recording_path(upload(client, filename, AUDIO, kind="call"))
    process_next_job(data_dir, transcriber)
    return path


def test_recording_page_offers_title_and_kind_edits_with_current_values_chosen(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call", title="Anna"))

    page = client.get(path).text

    assert path in form_actions(page)
    assert re.search(r'<input[^>]*name="title"[^>]*value="Anna"', page)
    assert re.search(rf'<option value="{kind_id(client, "call")}" selected>call</option>', page)


def test_editing_title_and_kind_shows_on_the_page_and_in_the_list(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call", title="Anna"))

    response = client.post(
        path, data={"title": "Anna about the flat", "kind_id": kind_id(client, "note")}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == path
    assert "<h1>Anna about the flat</h1>" in client.get(path).text
    [row] = list_rows(client)
    assert "Anna about the flat" in row
    assert "<td>note</td>" in row


def test_editing_only_the_title_keeps_the_kind(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call"))

    client.post(path, data={"title": "Renamed"})

    [row] = list_rows(client)
    assert "Renamed" in row
    assert "<td>call</td>" in row


def test_editing_only_the_kind_keeps_the_title(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call", title="Anna"))

    client.post(path, data={"kind_id": kind_id(client, "talk")})

    [row] = list_rows(client)
    assert "Anna" in row
    assert "<td>talk</td>" in row


def test_blank_title_is_refused_and_nothing_changes(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call", title="Anna"))

    response = client.post(path, data={"title": "   ", "kind_id": kind_id(client, "note")})

    assert response.status_code == 400
    assert 'class="error"' in response.text
    [row] = list_rows(client)
    assert "Anna" in row
    assert "<td>call</td>" in row


def test_unknown_kind_is_refused_and_nothing_changes(client):
    path = recording_path(upload(client, "anruf.m4a", AUDIO, kind="call", title="Anna"))

    response = client.post(path, data={"title": "Renamed", "kind_id": "999"})

    assert response.status_code == 400
    assert 'class="error"' in response.text
    [row] = list_rows(client)
    assert "Anna" in row
    assert "<td>call</td>" in row


def test_editing_an_unknown_recording_is_not_found(client):
    assert client.post("/recordings/999", data={"title": "x"}).status_code == 404


def test_delete_audio_asks_for_confirmation_before_acting(client, data_dir):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))

    page = client.get(path).text
    assert f'href="{path}/delete-audio"' in page
    assert f"{path}/delete-audio" not in form_actions(page)

    confirmation = client.get(f"{path}/delete-audio")
    assert confirmation.status_code == 200
    assert f"{path}/delete-audio" in form_actions(confirmation.text)
    assert f'href="{path}"' in confirmation.text
    assert len(audio_files(data_dir)) == 1


def test_delete_audio_removes_the_file_but_keeps_the_transcript(client, data_dir, transcriber):
    path = transcribed(client, data_dir, transcriber)

    response = client.post(f"{path}/delete-audio", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == path
    assert audio_files(data_dir) == []
    assert client.get(f"{path}/audio").status_code == 404
    page = client.get(path).text
    assert "Hello there." in page
    assert "<audio" not in page
    assert "delete-audio" not in page
    assert client.get(f"{path}/transcript.txt").text.strip() == "Hello there."


def test_deleting_audio_of_a_queued_recording_fails_its_job_with_a_clear_error(client, data_dir, transcriber):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    client.post(f"{path}/delete-audio")

    process_next_job(data_dir, transcriber)

    assert transcriber.calls == []
    assert status_on_page(client.get(path).text) == "Failed: The audio of this Recording was deleted"


def test_delete_recording_asks_for_confirmation_before_acting(client, data_dir):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))

    page = client.get(path).text
    assert f'href="{path}/delete"' in page
    assert f"{path}/delete" not in form_actions(page)

    confirmation = client.get(f"{path}/delete")
    assert confirmation.status_code == 200
    assert f"{path}/delete" in form_actions(confirmation.text)
    assert f'href="{path}"' in confirmation.text
    assert client.get(path).status_code == 200
    assert len(audio_files(data_dir)) == 1


def test_delete_recording_removes_everything(client, data_dir, transcriber):
    path = transcribed(client, data_dir, transcriber)
    kept = recording_path(upload(client, "other.m4a", wav_bytes(2)))

    response = client.post(f"{path}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get(path).status_code == 404
    assert client.get(f"{path}/audio").status_code == 404
    assert client.get(f"{path}/transcript.txt").status_code == 404
    assert len(audio_files(data_dir)) == 1
    [row] = list_rows(client)
    assert kept in row


def test_deleted_recording_can_be_uploaded_again(client, data_dir):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    client.post(f"{path}/delete")

    again = recording_path(upload(client, "anruf.m4a", AUDIO))

    assert status_on_page(client.get(again).text) == "Queued"
    assert len(list_rows(client)) == 1


def test_delete_recording_without_audio_still_removes_it(client, data_dir, transcriber):
    path = transcribed(client, data_dir, transcriber)
    client.post(f"{path}/delete-audio")

    client.post(f"{path}/delete")

    assert client.get(path).status_code == 404
    assert list_rows(client) == []


def test_deleting_a_recording_mid_transcription_drops_the_transcript(client, data_dir, transcriber):
    path = recording_path(upload(client, "anruf.m4a", AUDIO))
    transcriber.during = lambda: client.post(f"{path}/delete")

    process_next_job(data_dir, transcriber)

    assert client.get(path).status_code == 404
    assert list_rows(client) == []


def test_deleting_an_unknown_recording_is_not_found(client):
    for action in ("delete", "delete-audio"):
        assert client.get(f"/recordings/999/{action}").status_code == 404
        assert client.post(f"/recordings/999/{action}").status_code == 404
