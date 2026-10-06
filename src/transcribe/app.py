from pathlib import Path

from fastapi import FastAPI

from transcribe.db import init_db
from transcribe.transcriber import Transcriber

DB_FILENAME = "transcribe.sqlite3"


def create_app(data_dir: Path, transcriber: Transcriber) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "audio").mkdir(exist_ok=True)
    db_path = data_dir / DB_FILENAME
    init_db(db_path)

    app = FastAPI(title="Transcribe")
    app.state.data_dir = data_dir
    app.state.db_path = db_path
    app.state.transcriber = transcriber

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
