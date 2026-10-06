"""Production entrypoint: `uv run transcribe` or `uvicorn transcribe.main:build_app --factory`."""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from transcribe.app import create_app
from transcribe.transcriber import Transcription


class UnavailableTranscriber:
    """Stands in until the Whisper Transcriber is bound; every call fails loudly."""

    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcription:
        raise RuntimeError("No Whisper Transcriber is configured in this build")


def build_app() -> FastAPI:
    data_dir = Path(os.environ.get("TRANSCRIBE_DATA_DIR", "/data"))
    return create_app(data_dir=data_dir, transcriber=UnavailableTranscriber())


def serve() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("TRANSCRIBE_HOST", "0.0.0.0"),
        port=int(os.environ.get("TRANSCRIBE_PORT", "3002")),
    )
