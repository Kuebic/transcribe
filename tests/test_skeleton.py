import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from transcribe.app import DB_FILENAME, create_app
from transcribe.main import build_app
from transcribe.transcriber import Transcriber


def kind_names(data_dir: Path) -> list[str]:
    conn = sqlite3.connect(data_dir / DB_FILENAME)
    names = [row[0] for row in conn.execute("SELECT name FROM kinds ORDER BY id")]
    conn.close()
    return names


def test_healthz_returns_json(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_first_start_creates_data_directory_with_database(client, data_dir):
    assert (data_dir / "transcribe.sqlite3").is_file()


def test_seeded_kinds_are_created_once(data_dir, transcriber):
    for _ in range(2):
        with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)) as c:
            assert c.get("/healthz").status_code == 200

    assert kind_names(data_dir) == ["call", "lecture", "talk", "note"]


def test_schema_has_recordings_segments_and_jobs(client, data_dir):
    conn = sqlite3.connect(data_dir / DB_FILENAME)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert {"kinds", "recordings", "segments", "jobs"} <= tables


def test_fake_transcriber_satisfies_protocol(transcriber):
    assert isinstance(transcriber, Transcriber)


def test_deleted_seed_kind_is_not_recreated_on_restart(data_dir, transcriber):
    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)):
        pass
    conn = sqlite3.connect(data_dir / DB_FILENAME)
    with conn:
        conn.execute("DELETE FROM kinds WHERE name = 'note'")
    conn.close()

    with TestClient(create_app(data_dir=data_dir, transcriber=transcriber)):
        pass

    assert kind_names(data_dir) == ["call", "lecture", "talk"]


def test_server_entrypoint_builds_app_from_data_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_DATA_DIR", str(tmp_path / "served"))

    with TestClient(build_app()) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
    assert (tmp_path / "served" / "transcribe.sqlite3").is_file()
