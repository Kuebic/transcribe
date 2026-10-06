"""Pure functions turning a Transcript's Segments into the two copy formats.

Framework-free: the text endpoints, and through them the copy buttons, serve exactly what these return.
"""

from collections.abc import Sequence

from transcribe.transcriber import Segment

# A pause longer than this between two Segments starts a new paragraph.
PARAGRAPH_GAP_SECONDS = 2.0

# A paragraph that has reached this many words ends before the next Segment.
PARAGRAPH_WORDS = 250

ONE_HOUR = 3600


def plain(segments: Sequence[Segment]) -> str:
    """The Transcript as paragraphs separated by blank lines, without timestamps."""
    paragraphs: list[list[str]] = []
    word_count = 0
    previous_end: float | None = None
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        long_pause = previous_end is not None and segment.start - previous_end > PARAGRAPH_GAP_SECONDS
        if not paragraphs or long_pause or word_count >= PARAGRAPH_WORDS:
            paragraphs.append([])
            word_count = 0
        paragraphs[-1].append(text)
        word_count += len(text.split())
        previous_end = segment.end
    return "\n".join(" ".join(paragraph) + "\n" for paragraph in paragraphs)


def timestamped(segments: Sequence[Segment]) -> str:
    """One `[MM:SS] text` line per Segment; every line shows hours once any Segment starts past an hour."""
    with_hours = any(segment.start >= ONE_HOUR for segment in segments)
    return "".join(
        f"[{_clock(segment.start, with_hours)}] {segment.text.strip()}\n"
        for segment in segments
        if segment.text.strip()
    )


def _clock(seconds: float, with_hours: bool) -> str:
    minutes, secs = divmod(int(seconds), 60)
    if not with_hours:
        return f"{minutes:02}:{secs:02}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"
