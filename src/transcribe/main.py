"""Production entrypoint: `uv run transcribe` or `uvicorn transcribe.main:build_app --factory`."""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from transcribe.app import create_app
from transcribe.whisper import WhisperTranscriber


def build_app() -> FastAPI:
    data_dir = Path(os.environ.get("TRANSCRIBE_DATA_DIR", "/data"))
    return create_app(data_dir=data_dir, transcriber=WhisperTranscriber(models_dir=data_dir / "models"))


def serve() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("TRANSCRIBE_HOST", "0.0.0.0"),
        port=int(os.environ.get("TRANSCRIBE_PORT", "3002")),
    )
