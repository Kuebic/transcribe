import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from transcribe import copy_format, recordings
from transcribe.db import DB_FILENAME, connect, init_db
from transcribe.jobs import requeue_interrupted_jobs
from transcribe.limits import BodySizeLimit
from transcribe.media import probe_duration
from transcribe.transcriber import Segment, Transcriber
from transcribe.worker import Worker

MAX_UPLOAD_BYTES = 2 * 1024**3

DEFAULT_LANGUAGE = "en"

UNKNOWN_KIND_ERROR = "Choose one of the listed Kinds."

# Remembers the Kind of the last upload so the next upload form starts on it.
LAST_KIND_COOKIE = "last_kind_id"
LAST_KIND_MAX_AGE = 365 * 24 * 3600

# Not a Whisper code: asks Whisper to detect the language. Non-empty because an empty form
# field counts as missing and would fall back to the default language.
AUTO_DETECT = "auto"

# Whisper language codes offered at upload.
LANGUAGES = {
    AUTO_DETECT: "Detect automatically",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
    "pl": "Polish",
    "sv": "Swedish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

JOB_STATUS_LABELS = {
    "queued": "Queued",
    "transcribing": "Transcribing",
    "done": "Done",
    "failed": "Failed",
}

# Statuses a Job can still move on from; pages poll for a new status only while in one of these.
LIVE_STATUSES = ("queued", "transcribing")


def is_live(status: str | None) -> bool:
    return status in LIVE_STATUSES


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def format_timestamp(seconds: float) -> str:
    return f"[{copy_format.clock(seconds, with_hours=True)}]"


def create_app(
    data_dir: Path,
    transcriber: Transcriber,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    start_worker: bool = True,
) -> FastAPI:
    """Tests pass start_worker=False and drive the queue with process_next_job() themselves."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "audio").mkdir(exist_ok=True)
    db_path = data_dir / DB_FILENAME
    init_db(db_path)
    requeue_interrupted_jobs(data_dir)
    worker = Worker(data_dir, transcriber)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if start_worker:
            worker.start()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(title="Transcribe", lifespan=lifespan)
    app.state.data_dir = data_dir
    app.state.db_path = db_path
    app.state.transcriber = transcriber
    app.state.worker = worker
    app.add_middleware(BodySizeLimit, max_bytes=max_upload_bytes)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["duration"] = format_duration
    templates.env.filters["timestamp"] = format_timestamp
    templates.env.filters["status"] = lambda status: JOB_STATUS_LABELS.get(status, "—")
    templates.env.filters["language"] = lambda code: LANGUAGES.get(code or AUTO_DETECT, code)
    templates.env.tests["live"] = is_live

    @contextmanager
    def database() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def recording_or_404(conn: sqlite3.Connection, recording_id: int) -> sqlite3.Row:
        recording = recordings.get_recording(conn, recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="No such Recording")
        return recording

    def upload_form(
        request: Request,
        *,
        error: str | None = None,
        kind_id: int | None = None,
        title: str = "",
        language: str = DEFAULT_LANGUAGE,
    ) -> HTMLResponse:
        with database() as conn:
            kinds = recordings.list_kinds(conn)
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "kinds": kinds,
                "languages": LANGUAGES,
                "accepted_extensions": recordings.ACCEPTED_EXTENSIONS,
                "error": error,
                "selected_kind_id": kind_id,
                "title": title,
                "selected_language": language,
            },
            status_code=400 if error else 200,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def recording_list(request: Request):
        with database() as conn:
            rows = recordings.list_recordings(conn)
        return templates.TemplateResponse(request, "index.html", {"recordings": rows})

    @app.get("/upload", response_class=HTMLResponse)
    def upload_page(request: Request):
        last_kind_id = request.cookies.get(LAST_KIND_COOKIE, "")
        return upload_form(request, kind_id=int(last_kind_id) if last_kind_id.isdigit() else None)

    def store_upload(
        conn: sqlite3.Connection,
        upload: UploadFile,
        *,
        title: str | None,
        kind_id: int,
        language_requested: str | None,
    ) -> tuple[int, bool]:
        """Keep one uploaded file as a new Recording, unless its content is already stored.

        Returns the Recording's id and whether it is new. Without a title it is named after the file.
        """
        filename = upload.filename or ""
        staged = recordings.stage_audio(upload.file, data_dir)
        existing_id = recordings.find_recording_by_hash(conn, staged.content_hash)
        if existing_id is not None:
            staged.discard()
            return existing_id, False
        audio_path = recordings.keep_audio(staged, data_dir, recordings.audio_extension(filename))
        recording_id = recordings.create_recording(
            conn,
            original_filename=filename,
            content_hash=staged.content_hash,
            audio_path=audio_path,
            duration_seconds=probe_duration(data_dir / audio_path),
            title=title or recordings.title_from_filename(filename),
            kind_id=kind_id,
            language_requested=language_requested,
        )
        return recording_id, True

    @app.post("/upload")
    def upload(
        request: Request,
        files: Annotated[list[UploadFile], File()],
        kind_id: Annotated[int, Form()],
        title: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = DEFAULT_LANGUAGE,
    ):
        """One Recording per file; a file whose content is already stored opens the existing one."""
        retry = {"kind_id": kind_id, "title": title, "language": language}
        filenames = [f.filename or "" for f in files]
        unsupported = [name for name in filenames if recordings.audio_extension(name) is None]
        if unsupported:
            names = ", ".join(f"“{name}”" for name in unsupported)
            accepted = ", ".join(recordings.ACCEPTED_EXTENSIONS)
            return upload_form(
                request,
                error=f"{names} {'is' if len(unsupported) == 1 else 'are'} not a supported audio format. "
                f"Accepted: {accepted}.",
                **retry,
            )
        if language not in LANGUAGES:
            return upload_form(request, error=f"Unknown language “{language}”.", **retry)
        with database() as conn:
            if not recordings.kind_exists(conn, kind_id):
                return upload_form(request, error=UNKNOWN_KIND_ERROR, **retry)

        shared_fields = {
            # A typed title only fits a single file; several files are each named after their file.
            "title": title.strip() if len(files) == 1 else None,
            "kind_id": kind_id,
            "language_requested": None if language == AUTO_DETECT else language,
        }
        results = []
        with database() as conn:
            for f in files:
                recording_id, new = store_upload(conn, f, **shared_fields)
                results.append(
                    {"filename": f.filename, "new": new, "recording": recordings.get_recording(conn, recording_id)}
                )
        worker.wake()

        if len(results) == 1:
            response = RedirectResponse(f"/recordings/{results[0]['recording']['id']}", status_code=303)
        else:
            response = templates.TemplateResponse(request, "uploaded.html", {"results": results})
        response.set_cookie(
            LAST_KIND_COOKIE, str(kind_id), max_age=LAST_KIND_MAX_AGE, httponly=True, samesite="lax"
        )
        return response

    def recording_view(request: Request, recording_id: int, *, error: str | None = None) -> HTMLResponse:
        with database() as conn:
            recording = recording_or_404(conn, recording_id)
            segments = recordings.list_segments(conn, recording_id)
            kinds = recordings.list_kinds(conn)
        return templates.TemplateResponse(
            request,
            "recording.html",
            {"recording": recording, "segments": segments, "kinds": kinds, "error": error},
            status_code=400 if error else 200,
        )

    @app.get("/recordings/{recording_id}", response_class=HTMLResponse)
    def recording_page(request: Request, recording_id: int):
        return recording_view(request, recording_id)

    @app.post("/recordings/{recording_id}")
    def edit_recording(
        request: Request,
        recording_id: int,
        title: Annotated[str | None, Form()] = None,
        kind_id: Annotated[int | None, Form()] = None,
    ):
        """Change the title and/or Kind; a field left out keeps its value."""
        with database() as conn:
            recording_or_404(conn, recording_id)
            if title is not None:
                title = title.strip()
                if not title:
                    return recording_view(request, recording_id, error="The title cannot be blank.")
            if kind_id is not None and not recordings.kind_exists(conn, kind_id):
                return recording_view(request, recording_id, error=UNKNOWN_KIND_ERROR)
            recordings.update_recording(conn, recording_id, title=title, kind_id=kind_id)
        return RedirectResponse(f"/recordings/{recording_id}", status_code=303)

    def confirmation(request: Request, recording_id: int, action: str, question: str) -> HTMLResponse:
        """The page a delete link leads to; only its form's POST deletes anything."""
        with database() as conn:
            recording = recording_or_404(conn, recording_id)
        return templates.TemplateResponse(
            request, "confirm.html", {"recording": recording, "action": action, "question": question}
        )

    @app.get("/recordings/{recording_id}/delete-audio", response_class=HTMLResponse)
    def confirm_delete_audio(request: Request, recording_id: int):
        return confirmation(
            request,
            recording_id,
            "delete-audio",
            "Delete the audio of this Recording? The Transcript stays; the audio cannot be played again.",
        )

    @app.post("/recordings/{recording_id}/delete-audio")
    def delete_audio(recording_id: int):
        with database() as conn:
            recording_or_404(conn, recording_id)
            recordings.delete_audio(conn, data_dir, recording_id)
        return RedirectResponse(f"/recordings/{recording_id}", status_code=303)

    @app.get("/recordings/{recording_id}/delete", response_class=HTMLResponse)
    def confirm_delete_recording(request: Request, recording_id: int):
        return confirmation(
            request,
            recording_id,
            "delete",
            "Delete this Recording with its audio and Transcript? This cannot be undone.",
        )

    @app.post("/recordings/{recording_id}/delete")
    def delete_recording(recording_id: int):
        with database() as conn:
            recording_or_404(conn, recording_id)
            recordings.delete_recording(conn, data_dir, recording_id)
        return RedirectResponse("/", status_code=303)

    @app.get("/recordings/{recording_id}/audio", response_class=FileResponse)
    def audio(recording_id: int):
        """The original audio; FileResponse answers Range requests so the player can seek."""
        with database() as conn:
            audio_path = recording_or_404(conn, recording_id)["audio_path"]
        if audio_path is None or not (data_dir / audio_path).is_file():
            raise HTTPException(status_code=404, detail="This Recording has no audio")
        return FileResponse(data_dir / audio_path, media_type=recordings.audio_content_type(audio_path))

    def transcript_text(recording_id: int, render: Callable[[list[Segment]], str]) -> PlainTextResponse:
        with database() as conn:
            recording = recording_or_404(conn, recording_id)
            rows = recordings.list_segments(conn, recording_id)
        if recording["status"] != "done":
            raise HTTPException(status_code=404, detail="No Transcript until the Job is Done")
        segments = [Segment(row["start_seconds"], row["end_seconds"], row["text"]) for row in rows]
        return PlainTextResponse(render(segments))

    @app.get("/recordings/{recording_id}/transcript.txt", response_class=PlainTextResponse)
    def plain_transcript(recording_id: int):
        return transcript_text(recording_id, copy_format.plain)

    @app.get("/recordings/{recording_id}/transcript.timestamped.txt", response_class=PlainTextResponse)
    def timestamped_transcript(recording_id: int):
        return transcript_text(recording_id, copy_format.timestamped)

    @app.post("/recordings/{recording_id}/retry")
    def retry(recording_id: int):
        """Queue a fresh Job for a Failed Recording; does nothing while a Job is live or Done."""
        with database() as conn:
            recording_or_404(conn, recording_id)
            if recordings.retry_recording(conn, recording_id):
                worker.wake()
        return RedirectResponse(f"/recordings/{recording_id}", status_code=303)

    @app.get("/recordings/{recording_id}/status", response_class=HTMLResponse)
    def recording_status(request: Request, recording_id: int, reload: bool = False):
        """The polled status partial; with reload, a finished Job reloads the whole Recording page."""
        with database() as conn:
            recording = recording_or_404(conn, recording_id)
        response = templates.TemplateResponse(
            request, "status.html", {"recording": recording, "reload": reload}
        )
        if reload and not is_live(recording["status"]):
            response.headers["HX-Refresh"] = "true"
        return response

    return app
