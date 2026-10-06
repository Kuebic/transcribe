import re

from helpers import list_rows, recording_path, status_on_page, text_of, upload, wav_bytes
from transcribe.jobs import process_next_job
from transcribe.transcriber import Segment


def shows_utc_time(page: str, label: str) -> bool:
    pattern = rf"{label}</dt>\s*<dd>\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}} UTC</dd>"
    return re.search(pattern, page) is not None


def segments_on_page(page: str) -> list[str]:
    return [text_of(item) for item in re.findall(r'<li class="segment".*?</li>', page, re.S)]


def test_process_next_job_does_nothing_when_no_job_is_queued(client, data_dir, transcriber):
    assert process_next_job(data_dir, transcriber) is None
    assert transcriber.calls == []


def test_job_runs_to_done_and_segments_show_on_the_recording_page(client, data_dir, transcriber):
    transcriber.segments = [
        Segment(start=0.0, end=4.2, text=" Good morning, everyone."),
        Segment(start=4.2, end=65.5, text=" Today: entropy."),
        Segment(start=3725.0, end=3730.0, text=" Questions?"),
    ]
    path = recording_path(upload(client, "Week 3.m4a", wav_bytes(1)))

    assert process_next_job(data_dir, transcriber) is not None

    page = client.get(path).text
    assert status_on_page(page) == "Done"
    assert segments_on_page(page) == [
        "[00:00:00] Good morning, everyone.",
        "[00:00:04] Today: entropy.",
        "[01:02:05] Questions?",
    ]
    assert "Done" in list_rows(client)[0]


def test_transcriber_gets_the_stored_audio_and_requested_language(client, data_dir, transcriber):
    upload(client, "vortrag.mp3", wav_bytes(1), language="de")

    process_next_job(data_dir, transcriber)

    [(audio_path, language)] = transcriber.calls
    assert audio_path.parent == data_dir / "audio"
    assert audio_path.is_file()
    assert language == "de"


def test_automatic_language_detection_passes_no_language(client, data_dir, transcriber):
    upload(client, "unknown.mp3", wav_bytes(1), language="auto")

    process_next_job(data_dir, transcriber)

    [(_, language)] = transcriber.calls
    assert language is None


def test_recording_page_shows_requested_and_detected_language_and_model(client, data_dir, transcriber):
    transcriber.language = "fr"
    path = recording_path(upload(client, "cours.mp3", wav_bytes(1), language="auto"))

    process_next_job(data_dir, transcriber)

    page = client.get(path).text
    assert re.search(r"Detected language</dt>\s*<dd>French \(fr\)</dd>", page)
    assert re.search(r"Model</dt>\s*<dd>fake-whisper</dd>", page)


def test_oldest_queued_job_is_claimed_first(client, data_dir, transcriber):
    first = recording_path(upload(client, "first.wav", wav_bytes(1)))
    second = recording_path(upload(client, "second.wav", wav_bytes(2)))

    process_next_job(data_dir, transcriber)

    assert status_on_page(client.get(first).text) == "Done"
    assert status_on_page(client.get(second).text) == "Queued"

    process_next_job(data_dir, transcriber)

    assert status_on_page(client.get(second).text) == "Done"
    assert process_next_job(data_dir, transcriber) is None


def test_job_is_transcribing_with_a_start_time_while_the_transcriber_runs(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))
    seen = {}

    def look_at_page():
        seen["page"] = client.get(path).text

    transcriber.during = look_at_page
    process_next_job(data_dir, transcriber)

    assert status_on_page(seen["page"]).startswith("Transcribing")
    assert shows_utc_time(seen["page"], "Started")
    assert segments_on_page(seen["page"]) == []

    page = client.get(path).text
    assert shows_utc_time(page, "Started")
    assert shows_utc_time(page, "Finished")


def test_queued_recording_shows_no_transcript_yet(client, data_dir, transcriber):
    path = recording_path(upload(client, "clip.wav", wav_bytes(1)))

    page = client.get(path).text

    assert segments_on_page(page) == []
    assert "Started</dt>" not in page
    assert "Model</dt>" not in page


def test_raising_transcriber_stores_nothing_and_does_not_block_the_queue(client, data_dir, transcriber):
    broken = recording_path(upload(client, "broken.wav", wav_bytes(1)))
    healthy = recording_path(upload(client, "healthy.wav", wav_bytes(2)))
    transcriber.error = RuntimeError("decoder exploded")

    process_next_job(data_dir, transcriber)

    page = client.get(broken).text
    assert status_on_page(page) not in ("Done", "Queued", "Transcribing")
    assert segments_on_page(page) == []
    assert "Model</dt>" not in page

    transcriber.error = None
    process_next_job(data_dir, transcriber)

    assert status_on_page(client.get(healthy).text) == "Done"
    assert status_on_page(client.get(broken).text) not in ("Done", "Queued", "Transcribing")
