from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helpers import FakeTranscriber
from transcribe.app import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def client(data_dir: Path, transcriber: FakeTranscriber):
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber, start_worker=False)) as c:
        yield c
