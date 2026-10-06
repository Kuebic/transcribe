"""The production Transcriber: openai-whisper's CLI run as a subprocess with the owner's trusted flags."""

import json
import logging
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from transcribe.transcriber import Segment, Transcription

log = logging.getLogger(__name__)

MODEL = "large-v3"

# The CLI catches an error while transcribing a file, prints this on stdout and still exits 0.
SKIPPED = " due to "


def transcription_from_whisper_json(data: dict[str, Any]) -> Transcription:
    return Transcription(
        segments=[
            Segment(start=segment["start"], end=segment["end"], text=segment["text"])
            for segment in data["segments"]
        ],
        language=data.get("language"),
        model=MODEL,
    )


def failure_message(result: subprocess.CompletedProcess[str]) -> str:
    """The error Whisper reported: the one it skipped a file for, else the last line of its traceback."""
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("Skipping ") and SKIPPED in line:
            return line.split(SKIPPED, 1)[1]
    lines = [line for line in result.stderr.replace("\r", "\n").splitlines() if line.strip()]
    if lines:
        return lines[-1].strip()
    return f"Whisper exited with status {result.returncode} without writing a Transcript"


class WhisperTranscriber:
    """Runs `whisper` once per Recording; models download into models_dir once and are reused."""

    def __init__(
        self, models_dir: Path, command: Sequence[str] = (sys.executable, "-m", "whisper")
    ) -> None:
        self.models_dir = Path(models_dir)
        self.command = tuple(command)

    def transcribe(self, audio_path: Path, language: str | None = None) -> Transcription:
        audio_path = Path(audio_path)
        with tempfile.TemporaryDirectory(prefix="whisper-") as output_dir:
            args = [
                *self.command,
                str(audio_path),
                "--model", MODEL,
                "--model_dir", str(self.models_dir),
                "--output_format", "json",
                "--output_dir", output_dir,
                "--condition_on_previous_text", "False",
                "--fp16", "True",
                "--verbose", "False",
            ]
            if language:
                args += ["--language", language]
            try:
                result = subprocess.run(args, capture_output=True, text=True)
            except OSError as error:
                raise RuntimeError(f"Could not run Whisper: {error}") from error

            output = Path(output_dir) / f"{audio_path.stem}.json"
            if result.returncode != 0 or not output.exists():
                log.warning("Whisper failed on %s:\n%s%s", audio_path, result.stdout, result.stderr)
                raise RuntimeError(failure_message(result))
            return transcription_from_whisper_json(json.loads(output.read_text()))
