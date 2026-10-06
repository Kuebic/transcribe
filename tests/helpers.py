"""HTTP helpers shared by the test modules: upload audio and read the pages the owner sees."""

import io
import re
import wave

from fastapi.testclient import TestClient


def wav_bytes(seconds: float, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def kind_id(client: TestClient, name: str) -> str:
    page = client.get("/upload").text
    match = re.search(rf'<option value="(\d+)"[^>]*>{name}</option>', page)
    assert match, f"Kind {name!r} not offered on the upload page"
    return match.group(1)


def upload(client: TestClient, filename: str, content: bytes, kind: str = "lecture", **fields):
    data = {"kind_id": kind_id(client, kind), **fields}
    return client.post(
        "/upload",
        data=data,
        files={"files": (filename, content, "application/octet-stream")},
        follow_redirects=False,
    )


def recording_path(response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert re.fullmatch(r"/recordings/\d+", location)
    return location


def list_rows(client: TestClient) -> list[str]:
    return re.findall(r"<tr class=\"recording\".*?</tr>", client.get("/").text, re.S)
