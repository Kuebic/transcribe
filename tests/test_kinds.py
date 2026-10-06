import re

import pytest

from helpers import kind_id, list_rows, recording_path, text_of, upload, wav_bytes

SEEDED = ("call", "lecture", "talk", "note")


def kinds_on_page(client) -> list[str]:
    page = client.get("/kinds").text
    return re.findall(r'<form[^>]*action="/kinds/\d+">\s*<input[^>]*name="name"[^>]*value="([^"]*)"', page)


def offered_at_upload(client) -> list[str]:
    return re.findall(r'<option value="\d+"[^>]*>([^<]*)</option>', client.get("/upload").text)


def form_actions(page: str) -> list[str]:
    return re.findall(r'<form[^>]*\baction="([^"]+)"', page)


def kind_on_recording_page(page: str) -> str:
    return text_of(re.search(r"<dt>Kind</dt><dd>(.*?)</dd>", page, re.S).group(1))


def test_kinds_page_lists_the_seeded_kinds_and_is_linked_from_every_page(client):
    response = client.get("/kinds")

    assert response.status_code == 200
    assert kinds_on_page(client) == list(SEEDED)
    assert 'href="/kinds"' in client.get("/").text
    assert "/kinds" in form_actions(response.text)


def test_kinds_page_shows_how_many_recordings_have_each_kind(client):
    upload(client, "a.m4a", wav_bytes(1), kind="call")
    upload(client, "b.m4a", wav_bytes(2), kind="call")

    page = text_of(client.get("/kinds").text)

    assert "2 Recordings" in page
    assert "No Recordings" in page


def test_adding_a_kind_lists_it_and_offers_it_at_upload(client):
    response = client.post("/kinds", data={"name": "  sermon  "}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/kinds"
    assert kinds_on_page(client) == [*SEEDED, "sermon"]
    assert "sermon" in offered_at_upload(client)
    assert recording_path(upload(client, "a.m4a", wav_bytes(1), kind="sermon"))


@pytest.mark.parametrize("name", ["call", "Call", " CALL "])
def test_adding_a_duplicate_kind_is_refused(client, name):
    response = client.post("/kinds", data={"name": name})

    assert response.status_code == 400
    assert "already exists" in text_of(response.text)
    assert kinds_on_page(client) == list(SEEDED)


def test_adding_a_blank_kind_is_refused(client):
    response = client.post("/kinds", data={"name": "   "})

    assert response.status_code == 400
    assert 'class="error"' in response.text
    assert kinds_on_page(client) == list(SEEDED)


def test_renaming_a_kind_shows_the_new_name_on_every_recording_with_it(client):
    first = recording_path(upload(client, "a.m4a", wav_bytes(1), kind="call"))
    upload(client, "b.m4a", wav_bytes(2), kind="call")
    other = recording_path(upload(client, "c.m4a", wav_bytes(3), kind="lecture"))

    response = client.post(f"/kinds/{kind_id(client, 'call')}", data={"name": "phone call"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/kinds"
    assert kinds_on_page(client) == ["phone call", "lecture", "talk", "note"]
    kinds_in_list = [re.search(r"<td>([^<]*)</td>", row).group(1) for row in list_rows(client)]
    assert sorted(kinds_in_list) == ["lecture", "phone call", "phone call"]
    assert kind_on_recording_page(client.get(first).text) == "phone call"
    assert kind_on_recording_page(client.get(other).text) == "lecture"


def test_renaming_a_kind_to_another_kinds_name_is_refused(client):
    response = client.post(f"/kinds/{kind_id(client, 'call')}", data={"name": "Lecture"})

    assert response.status_code == 400
    assert "already exists" in text_of(response.text)
    assert kinds_on_page(client) == list(SEEDED)


def test_renaming_a_kind_to_a_different_case_of_its_own_name_is_allowed(client):
    response = client.post(f"/kinds/{kind_id(client, 'call')}", data={"name": "Call"})

    assert response.status_code == 200
    assert kinds_on_page(client) == ["Call", "lecture", "talk", "note"]


def test_renaming_a_kind_to_blank_is_refused(client):
    response = client.post(f"/kinds/{kind_id(client, 'call')}", data={"name": " "})

    assert response.status_code == 400
    assert kinds_on_page(client) == list(SEEDED)


def test_deleting_a_kind_asks_for_confirmation_before_acting(client):
    call = kind_id(client, "call")
    assert f'href="/kinds/{call}/delete"' in client.get("/kinds").text
    assert f"/kinds/{call}/delete" not in form_actions(client.get("/kinds").text)

    confirmation = client.get(f"/kinds/{call}/delete")

    assert confirmation.status_code == 200
    assert f"/kinds/{call}/delete" in form_actions(confirmation.text)
    assert 'href="/kinds"' in confirmation.text
    assert kinds_on_page(client) == list(SEEDED)


def test_deleting_an_unused_kind_removes_it(client):
    response = client.post(f"/kinds/{kind_id(client, 'talk')}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/kinds"
    assert kinds_on_page(client) == ["call", "lecture", "note"]
    assert "talk" not in offered_at_upload(client)


def test_deleting_a_kind_in_use_is_refused_with_a_message(client):
    path = recording_path(upload(client, "a.m4a", wav_bytes(1), kind="call"))
    call = kind_id(client, "call")

    assert f'href="/kinds/{call}/delete"' not in client.get("/kinds").text
    response = client.post(f"/kinds/{call}/delete")

    assert response.status_code == 400
    assert "1 Recording has this Kind" in text_of(response.text)
    assert kinds_on_page(client) == list(SEEDED)
    assert kind_on_recording_page(client.get(path).text) == "call"


def test_a_kind_can_be_deleted_once_its_last_recording_is(client):
    path = recording_path(upload(client, "a.m4a", wav_bytes(1), kind="call"))
    call = kind_id(client, "call")
    client.post(f"{path}/delete")

    assert client.post(f"/kinds/{call}/delete").status_code == 200
    assert kinds_on_page(client) == ["lecture", "talk", "note"]


def test_unknown_kinds_are_not_found(client):
    assert client.post("/kinds/999", data={"name": "x"}).status_code == 404
    assert client.get("/kinds/999/delete").status_code == 404
    assert client.post("/kinds/999/delete").status_code == 404
    assert client.get("/?kind=999").status_code == 404


def test_list_can_be_filtered_to_one_kind(client):
    call_path = recording_path(upload(client, "a.m4a", wav_bytes(1), kind="call"))
    lecture_path = recording_path(upload(client, "b.m4a", wav_bytes(2), kind="lecture"))

    page = client.get(f"/?kind={kind_id(client, 'call')}").text
    rows = re.findall(r"<tr class=\"recording\".*?</tr>", page, re.S)

    assert len(rows) == 1
    assert call_path in rows[0]
    assert lecture_path not in page
    assert len(list_rows(client)) == 2


def test_list_offers_a_filter_link_for_every_kind_and_marks_the_chosen_one(client):
    upload(client, "a.m4a", wav_bytes(1), kind="call")
    lecture = kind_id(client, "lecture")

    unfiltered = client.get("/").text
    for name in SEEDED:
        assert f'href="/?kind={kind_id(client, name)}"' in unfiltered
    assert re.search(r'<a href="/" aria-current="page">All</a>', unfiltered)

    filtered = client.get(f"/?kind={lecture}").text
    assert re.search(rf'<a href="/\?kind={lecture}" aria-current="page">lecture</a>', filtered)
    assert "No lecture Recordings yet" in text_of(filtered)
