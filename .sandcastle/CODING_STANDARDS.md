# Coding Standards

The reviewer loads this file on every review cycle. Keep it short; every line here costs review attention.

## Vocabulary

- Use the nouns from `GLOSSARY.md`: Recording, Kind, Transcript, Segment, Job.
- Never introduce the avoided synonyms as identifiers or UI text: upload, file, audio, session (for Recording); folder, type, category, tag (for Kind); raw transcript, output, caption (for Transcript); line, chunk, cue (for Segment); task, process, run (for Job).
- Respect `docs/adr/0001-lan-only-no-auth.md`: no auth, no sessions, no CSRF, no CORS. Flag any change that would need them.

## Shape

- One FastAPI process, SQLite only, Job queue is a table, one worker thread. No Redis, Postgres, Celery, or separate containers.
- Server-rendered Jinja pages; HTMX for partial refresh; hand-written JavaScript only for the player/Segment sync, upload progress, and clipboard. No bundler, no npm, no build step.
- The `Transcriber` protocol and the copy-format functions are framework-free modules. Nothing in them imports FastAPI, SQLite, or the filesystem layout.
- App is built by one factory taking the data directory and the Transcriber. No module-level singletons for DB, config, or worker.

## Tests

- Tests exercise the app through HTTP with the ASGI test client and assert on responses and on what the next request can see. They do not query the database or poke worker internals.
- Tests never need a GPU. The fake Transcriber returns canned Segments or raises; the production Transcriber has one env-gated smoke test only.
- Job progression in tests goes through `process_next_job()` directly, except the single test that proves the worker thread drains the queue.
- Copy-format tests are byte-exact against fixed Segment lists.
- Red → Green → Refactor: a failing test lands before the implementation.

## UI

- Phone-first: every page usable one-handed on a phone screen over home Wi-Fi. Large tap targets for upload, copy, and Segment seek. Destructive actions confirm.
- Status is visible without opening a Recording: list rows show title, Kind, duration, upload date, status.
- Copy buttons give visible confirmation after the clipboard write.

## Python

- Python 3.12, `uv` for dependencies and running (`uv run pytest`).
- Type hints on public functions; no `Any` where a concrete type is known.
- Small functions, early returns, no nested ternaries. Clarity over brevity.
- No commented-out code, no TODO comments in committed code.
