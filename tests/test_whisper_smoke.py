"""Runs the real Whisper Transcriber on the GPU; skipped unless TRANSCRIBE_SMOKE_AUDIO names an audio file.

Run by hand on the GPU box, inside the image so CUDA, ffmpeg and Whisper are the ones in production:

    docker compose run --rm -e TRANSCRIBE_SMOKE_AUDIO=/data/smoke.m4a transcribe \\
        pytest tests/test_whisper_smoke.py

Models are cached in TRANSCRIBE_SMOKE_MODELS_DIR, by default /data/models, the same cache the app uses.
"""

import os
from pathlib import Path

import pytest

from transcribe.whisper import MODEL, WhisperTranscriber

AUDIO = os.environ.get("TRANSCRIBE_SMOKE_AUDIO")

pytestmark = pytest.mark.skipif(not AUDIO, reason="TRANSCRIBE_SMOKE_AUDIO is not set")


def test_real_whisper_transcribes_and_reuses_its_cached_model():
    models_dir = Path(os.environ.get("TRANSCRIBE_SMOKE_MODELS_DIR", "/data/models"))
    whisper = WhisperTranscriber(models_dir=models_dir)

    transcription = whisper.transcribe(Path(AUDIO))

    assert transcription.segments
    assert [s.start for s in transcription.segments] == sorted(s.start for s in transcription.segments)
    assert any(s.text.strip() for s in transcription.segments)
    assert transcription.language
    assert transcription.model == MODEL

    model_file = models_dir / f"{MODEL}.pt"
    downloaded_at = model_file.stat().st_mtime
    whisper.transcribe(Path(AUDIO), transcription.language)
    assert model_file.stat().st_mtime == downloaded_at
