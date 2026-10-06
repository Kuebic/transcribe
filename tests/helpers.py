"""Shared by the test modules: a fake Transcriber, uploading audio and reading the pages the owner sees."""

import io
import re
import wave
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from transcribe.transcriber import Segment, Transcription


class FakeTranscriber:
    """Returns canned Segments; `during` runs mid-transcription, `error` is raised instead of returning."""

    def __init__(
        self,
        segments: list[Segment] | None = None,
        language: str = "en",
        model: str = "fake-whisper",
    ):
        self.segments = segments or [Segment(start=0.0, end=1.5, text="Hello there.")]
        self.language = language
        self.model = model
        self.during: Callable[[], None] | None = None
        self.error: BaseException | None = None
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcription:
        self.calls.append((audio_path, language))
        if self.during:
            self.during()
        if self.error:
            raise self.error
        return Transcription(segments=list(self.segments), language=self.language, model=self.model)


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
    return upload_many(client, {filename: content}, kind, **fields)


def upload_many(client: TestClient, files: dict[str, bytes], kind: str = "lecture", **fields):
    data = {"kind_id": kind_id(client, kind), **fields}
    return client.post(
        "/upload",
        data=data,
        files=[("files", (name, content, "application/octet-stream")) for name, content in files.items()],
        follow_redirects=False,
    )


def recording_path(response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert re.fullmatch(r"/recordings/\d+", location)
    return location


def list_rows(client: TestClient, path: str = "/") -> list[str]:
    return re.findall(r"<tr class=\"recording\".*?</tr>", client.get(path).text, re.S)


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def status_on_page(page: str) -> str:
    return text_of(re.search(r'<dd class="status">(.*?)</dd>', page, re.S).group(1))
