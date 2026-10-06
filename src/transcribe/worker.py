"""The single background thread that drains the Job queue, one Job at a time, in upload order."""

import logging
import threading
from pathlib import Path

from transcribe.jobs import process_next_job
from transcribe.transcriber import Transcriber

log = logging.getLogger(__name__)

# How long an idle worker sleeps before looking at the queue again when nobody wakes it.
IDLE_SECONDS = 5.0


class Worker:
    def __init__(self, data_dir: Path, transcriber: Transcriber, *, idle_seconds: float = IDLE_SECONDS):
        self.data_dir = data_dir
        self.transcriber = transcriber
        self.idle_seconds = idle_seconds
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="transcribe-worker", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Look at the queue now instead of at the end of the idle wait."""
        self._wake.set()

    def stop(self, timeout: float = 10.0) -> None:
        """Stop after the current Job; a Job still running at the timeout is requeued on next start."""
        self._stopping.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            try:
                job_id = process_next_job(self.data_dir, self.transcriber)
            except Exception:
                log.exception("Worker could not process the next Job")
                job_id = None
            if job_id is None:
                self._wake.wait(self.idle_seconds)
