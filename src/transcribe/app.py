import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from transcribe import recordings
from transcribe.db import connect, init_db
from transcribe.limits import BodySizeLimit
from transcribe.media import probe_duration
from transcribe.transcriber import Transcriber

DB_FILENAME = "transcribe.sqlite3"

MAX_UPLOAD_BYTES = 2 * 1024**3

DEFAULT_LANGUAGE = "en"

# Whisper language codes offered at upload; the empty code asks Whisper to detect the language.
LANGUAGES = {
    "": "Detect automatically",
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


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def create_app(
    data_dir: Path,
    transcriber: Transcriber,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "audio").mkdir(exist_ok=True)
    db_path = data_dir / DB_FILENAME
    init_db(db_path)

    app = FastAPI(title="Transcribe")
    app.state.data_dir = data_dir
    app.state.db_path = db_path
    app.state.transcriber = transcriber
    app.add_middleware(BodySizeLimit, max_bytes=max_upload_bytes)

    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["duration"] = format_duration
    templates.env.filters["status"] = lambda status: JOB_STATUS_LABELS.get(status, "—")
    templates.env.filters["language"] = lambda code: LANGUAGES.get(code or "", code)

    @contextmanager
    def database() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

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
        return upload_form(request)

    @app.post("/upload")
    def upload(
        request: Request,
        files: Annotated[UploadFile, File()],
        kind_id: Annotated[int, Form()],
        title: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = DEFAULT_LANGUAGE,
    ):
        filename = files.filename or ""
        retry = {"kind_id": kind_id, "title": title, "language": language}
        extension = recordings.audio_extension(filename)
        if extension is None:
            accepted = ", ".join(recordings.ACCEPTED_EXTENSIONS)
            return upload_form(
                request,
                error=f"“{filename}” is not a supported audio format. Accepted: {accepted}.",
                **retry,
            )
        if language not in LANGUAGES:
            return upload_form(request, error=f"Unknown language “{language}”.", **retry)
        with database() as conn:
            if not recordings.kind_exists(conn, kind_id):
                return upload_form(request, error="Choose one of the listed Kinds.", **retry)

        staged = recordings.stage_audio(files.file, data_dir)
        with database() as conn:
            existing_id = recordings.find_recording_by_hash(conn, staged.content_hash)
            if existing_id is not None:
                staged.discard()
                return RedirectResponse(f"/recordings/{existing_id}", status_code=303)

            audio_path = recordings.keep_audio(staged, data_dir, extension)
            recording_id = recordings.create_recording(
                conn,
                title=title.strip() or recordings.title_from_filename(filename),
                kind_id=kind_id,
                original_filename=filename,
                content_hash=staged.content_hash,
                audio_path=audio_path,
                duration_seconds=probe_duration(data_dir / audio_path),
                language_requested=language or None,
            )
        return RedirectResponse(f"/recordings/{recording_id}", status_code=303)

    @app.get("/recordings/{recording_id}", response_class=HTMLResponse)
    def recording_page(request: Request, recording_id: int):
        with database() as conn:
            recording = recordings.get_recording(conn, recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="No such Recording")
        return templates.TemplateResponse(request, "recording.html", {"recording": recording})

    return app
