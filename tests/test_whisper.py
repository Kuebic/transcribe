import json
import sys
from pathlib import Path

import pytest

from transcribe.main import build_app
from transcribe.transcriber import Segment, Transcriber
from transcribe.whisper import MODEL, WhisperTranscriber, transcription_from_whisper_json

FAKE_WHISPER = Path(__file__).parent / "fake_whisper.py"
SAMPLE = Path(__file__).parent / "fixtures" / "whisper_large_v3.json"


@pytest.fixture
def argv_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_WHISPER_ARGV", str(path))
    return path


@pytest.fixture
def whisper(tmp_path) -> WhisperTranscriber:
    return WhisperTranscriber(models_dir=tmp_path / "models", command=(sys.executable, str(FAKE_WHISPER)))


@pytest.fixture
def audio(tmp_path) -> Path:
    path = tmp_path / "3f2a9c.m4a"
    path.write_bytes(b"not really audio")
    return path


def option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def test_whisper_json_becomes_ordered_segments_and_detected_language():
    transcription = transcription_from_whisper_json(json.loads(SAMPLE.read_text()))

    assert transcription.segments == [
        Segment(start=0.0, end=4.2, text=" Good morning, everyone."),
        Segment(start=4.2, end=9.86, text=" Today we're going to talk about entropy."),
        Segment(start=32.5, end=35.12, text=" Any questions before we start?"),
    ]
    assert transcription.language == "en"
    assert transcription.model == MODEL == "large-v3"


def test_whisper_transcriber_satisfies_protocol(whisper):
    assert isinstance(whisper, Transcriber)


def test_runs_whisper_with_the_trusted_flags_and_caches_models_in_the_models_dir(
    whisper, audio, argv_file, tmp_path
):
    transcription = whisper.transcribe(audio, "de")

    argv = json.loads(argv_file.read_text())
    assert argv[0] == str(audio)
    assert option(argv, "--model") == "large-v3"
    assert option(argv, "--model_dir") == str(tmp_path / "models")
    assert option(argv, "--output_format") == "json"
    assert option(argv, "--condition_on_previous_text") == "False"
    assert option(argv, "--fp16") == "True"
    assert option(argv, "--language") == "de"
    assert [segment.text for segment in transcription.segments] == [
        " Good morning, everyone.",
        " Today we're going to talk about entropy.",
        " Any questions before we start?",
    ]


def test_no_language_lets_whisper_detect_it(whisper, audio, argv_file):
    transcription = whisper.transcribe(audio, None)

    assert "--language" not in json.loads(argv_file.read_text())
    assert transcription.language == "en"


def test_error_whisper_skips_past_is_raised_with_its_message(whisper, audio, argv_file, monkeypatch):
    monkeypatch.setenv(
        "FAKE_WHISPER_SKIP", "OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB"
    )

    with pytest.raises(RuntimeError) as raised:
        whisper.transcribe(audio, "en")

    assert str(raised.value) == "OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB"


def test_whisper_crashing_is_raised_with_the_last_line_of_its_traceback(
    whisper, audio, argv_file, monkeypatch
):
    monkeypatch.setenv(
        "FAKE_WHISPER_CRASH", "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB"
    )

    with pytest.raises(RuntimeError) as raised:
        whisper.transcribe(audio, "en")

    assert str(raised.value) == "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB"


def test_missing_whisper_is_raised_as_an_error(tmp_path, audio):
    whisper = WhisperTranscriber(models_dir=tmp_path / "models", command=(str(tmp_path / "no-whisper"),))

    with pytest.raises(RuntimeError):
        whisper.transcribe(audio, "en")


def test_app_started_normally_transcribes_with_whisper_caching_models_under_the_data_dir(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRANSCRIBE_DATA_DIR", str(tmp_path / "data"))

    transcriber = build_app().state.transcriber

    assert isinstance(transcriber, WhisperTranscriber)
    assert transcriber.models_dir == tmp_path / "data" / "models"
