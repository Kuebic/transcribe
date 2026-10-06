"""The Transcriber seam: the only part of the app that needs a GPU.

Framework-free on purpose so the web app, the worker and tests can all import it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcription:
    segments: list[Segment]
    language: str | None
    model: str


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcription: ...
