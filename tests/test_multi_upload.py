import re

from helpers import list_rows, recording_path, status_on_page, text_of, upload, upload_many, wav_bytes


def outcomes(page: str) -> dict[str, tuple[str, str]]:
    """Each uploaded filename on the result page with its outcome and the Recording it links to."""
    rows = re.findall(r'<tr class="uploaded">(.*?)</tr>', page, re.S)
    result = {}
    for row in rows:
        filename, outcome, _ = (text_of(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S))
        result[filename] = (outcome, re.search(r'href="(/recordings/\d+)"', row).group(1))
    return result


def selected_kind(client) -> str | None:
    match = re.search(r'<option value="\d+" selected>(\w+)</option>', client.get("/upload").text)
    return match.group(1) if match else None


def test_several_files_become_one_queued_recording_each(client):
    response = upload_many(client, {"a.wav": wav_bytes(1), "b.mp3": wav_bytes(2), "c.m4a": wav_bytes(3)})

    assert response.status_code == 200
    result = outcomes(response.text)
    assert set(result) == {"a.wav", "b.mp3", "c.m4a"}
    assert {outcome for outcome, _ in result.values()} == {"New"}
    assert len({path for _, path in result.values()}) == 3
    for _, path in result.values():
        assert status_on_page(client.get(path).text) == "Queued"
    assert len(list_rows(client)) == 3


def test_each_of_several_files_is_titled_after_its_filename(client):
    upload_many(client, {"Week 1.wav": wav_bytes(1), "Week 2.wav": wav_bytes(2)}, title="Ignored")

    titles = sorted(text_of(re.search(r"<a [^>]*>(.*?)</a>", row).group(1)) for row in list_rows(client))
    assert titles == ["Week 1", "Week 2"]


def test_result_page_tells_new_files_from_duplicates(client):
    existing = recording_path(upload(client, "earlier.wav", wav_bytes(1)))

    response = upload_many(
        client,
        {"renamed earlier.wav": wav_bytes(1), "fresh.wav": wav_bytes(2), "fresh copy.wav": wav_bytes(2)},
    )

    result = outcomes(response.text)
    assert result["renamed earlier.wav"] == ("Already uploaded", existing)
    assert result["fresh.wav"][0] == "New"
    assert result["fresh copy.wav"] == ("Already uploaded", result["fresh.wav"][1])
    assert len(list_rows(client)) == 2


def test_one_unsupported_file_rejects_the_whole_upload(client, data_dir):
    response = upload_many(client, {"good.wav": wav_bytes(1), "notes.txt": b"not audio"})

    assert response.status_code == 400
    assert "notes.txt" in response.text
    assert list_rows(client) == []
    assert list((data_dir / "audio").iterdir()) == []


def test_upload_form_accepts_several_files_and_shows_progress(client):
    page = client.get("/upload").text

    assert re.search(r'<input type="file" name="files" multiple', page)
    # audio/* first: Android's picker matches the MIME an app indexed a file with, not its
    # extension, so an extension-only list greys out recordings saved to Downloads.
    assert 'accept="audio/*,.m4a,' in page
    assert '<script src="/static/upload.js" defer></script>' in page
    assert "<progress" in page
    assert client.get("/static/upload.js").status_code == 200


def test_upload_form_preselects_the_kind_used_last(client):
    assert selected_kind(client) is None

    upload(client, "call.wav", wav_bytes(1), kind="talk")
    assert selected_kind(client) == "talk"

    upload_many(client, {"x.wav": wav_bytes(2), "y.wav": wav_bytes(3)}, kind="call")
    assert selected_kind(client) == "call"


def test_duplicate_upload_still_remembers_the_kind(client):
    upload(client, "a.wav", wav_bytes(1), kind="talk")
    upload(client, "a again.wav", wav_bytes(1), kind="note")

    assert selected_kind(client) == "note"


def test_rejected_upload_does_not_change_the_remembered_kind(client):
    upload(client, "a.wav", wav_bytes(1), kind="talk")
    upload(client, "notes.txt", b"not audio", kind="note")

    assert selected_kind(client) == "talk"


def test_remembered_kind_that_no_longer_exists_is_ignored(client):
    for value in ("9999", "not-a-number"):
        client.cookies.set("last_kind_id", value)
        page = client.get("/upload")

        assert page.status_code == 200
        assert selected_kind(client) is None
