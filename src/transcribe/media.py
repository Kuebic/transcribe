"""Reads facts about audio with ffprobe, which ships alongside Whisper's ffmpeg."""

import subprocess
from pathlib import Path


def probe_duration(audio_path: Path) -> float | None:
    """Duration in seconds, or None when ffprobe is missing or cannot read the audio."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
