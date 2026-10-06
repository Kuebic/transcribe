from transcribe.copy_format import PARAGRAPH_GAP_SECONDS, PARAGRAPH_WORDS, plain, timestamped
from transcribe.transcriber import Segment

LECTURE = [
    Segment(start=0.0, end=2.5, text=" Good morning, everyone."),
    Segment(start=2.5, end=5.0, text=" Today we talk about entropy."),
    Segment(start=5.0, end=7.0, text=" It measures surprise."),
    Segment(start=9.5, end=12.0, text=" Let us start with coins."),
    Segment(start=14.0, end=15.0, text=" Heads or tails?"),
]


def words(count: int, prefix: str) -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def test_plain_breaks_paragraphs_only_on_gaps_longer_than_two_seconds():
    assert PARAGRAPH_GAP_SECONDS == 2.0
    assert plain(LECTURE) == (
        "Good morning, everyone. Today we talk about entropy. It measures surprise.\n"
        "\n"
        "Let us start with coins. Heads or tails?\n"
    )


def test_plain_starts_a_new_paragraph_once_one_reaches_the_word_limit():
    assert PARAGRAPH_WORDS == 250
    segments = [
        Segment(start=i * 10.0, end=i * 10.0 + 10.0, text=f" {words(100, chr(ord('a') + i))}")
        for i in range(4)
    ]

    assert plain(segments) == (
        f"{words(100, 'a')} {words(100, 'b')} {words(100, 'c')}\n"
        "\n"
        f"{words(100, 'd')}\n"
    )


def test_plain_skips_empty_segments():
    segments = [Segment(0.0, 1.0, " One."), Segment(1.0, 2.0, "  "), Segment(2.0, 3.0, "Two.")]

    assert plain(segments) == "One. Two.\n"


def test_timestamped_drops_hours_when_the_transcript_is_under_an_hour():
    assert timestamped(LECTURE) == (
        "[00:00] Good morning, everyone.\n"
        "[00:02] Today we talk about entropy.\n"
        "[00:05] It measures surprise.\n"
        "[00:09] Let us start with coins.\n"
        "[00:14] Heads or tails?\n"
    )


def test_timestamped_shows_hours_on_every_line_once_the_transcript_passes_an_hour():
    segments = [
        Segment(start=0.0, end=4.2, text=" Good morning."),
        Segment(start=65.9, end=70.0, text=" Entropy."),
        Segment(start=3725.0, end=3730.0, text=" Questions?"),
    ]

    assert timestamped(segments) == (
        "[00:00:00] Good morning.\n"
        "[00:01:05] Entropy.\n"
        "[01:02:05] Questions?\n"
    )


def test_empty_transcript_gives_empty_text():
    assert plain([]) == ""
    assert timestamped([]) == ""
