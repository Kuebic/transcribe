from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from transcribe.app import create_app
from transcribe.transcriber import Segment, Transcription


class FakeTranscriber:
    def __init__(self, segments: list[Segment] | None = None, language: str = "en"):
        self.segments = segments or [Segment(start=0.0, end=1.5, text="Hello there.")]
        self.language = language
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcription:
        self.calls.append((audio_path, language))
        return Transcription(segments=list(self.segments), language=self.language)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def client(data_dir: Path, transcriber: FakeTranscriber):
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)) as c:
        yield c
