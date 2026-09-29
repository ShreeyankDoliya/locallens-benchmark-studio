"""SQLite checkpoints: each terminal attempt and task result commit atomically."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .models import canonical


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            status TEXT NOT NULL, snapshot TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS results (
            run_id TEXT NOT NULL, model_id TEXT NOT NULL, task_id TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(run_id, model_id, task_id));
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, model_id TEXT NOT NULL,
            task_id TEXT NOT NULL, payload TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def writer_lock(self):
        # OS releases the lock even on SIGKILL. No stale PID or manual unlock needed.
        lock_path = self.path.with_suffix(self.path.suffix + ".lockfile")
        with lock_path.open("a+b") as handle:
            try:
                if __import__("os").name == "nt":
                    import msvcrt
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("another runner is using this database") from exc
            try:
                yield
            finally:
                if __import__("os").name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def create(self, run_id: str, snapshot: dict) -> None:
        timestamp = now()
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (run_id, timestamp, timestamp, "pending", canonical(snapshot)))

    def run(self, run_id: str) -> dict:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown run: {run_id}")
        result = dict(row)
        result["snapshot"] = json.loads(result["snapshot"])
        return result

    def status(self, run_id: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (status, now(), run_id))

    def results(self, run_id: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM results WHERE run_id=? ORDER BY model_id, task_id", (run_id,))]

    def attempts(self, run_id: str, model_id: str, task_id: str) -> list[dict]:
        return [dict(json.loads(r["payload"]), id=r["id"]) for r in self.db.execute("SELECT id,payload FROM attempts WHERE run_id=? AND model_id=? AND task_id=? ORDER BY id", (run_id, model_id, task_id))]

    def begin_attempt(self, run_id: str, model_id: str, task_id: str) -> tuple[int, dict]:
        attempt = {"started_at": now(), "status": "running"}
        with self.db:
            cursor = self.db.execute("INSERT INTO attempts(run_id,model_id,task_id,payload) VALUES(?,?,?,?)", (run_id, model_id, task_id, canonical(attempt)))
        return cursor.lastrowid, attempt

    def finish_attempt(self, attempt_id: int, attempt: dict, result: dict | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE attempts SET payload=? WHERE id=?", (canonical(attempt), attempt_id))
            if result:
                self.db.execute("INSERT INTO results VALUES (?,?,?,?)", (result["run_id"], result["model_id"], result["task_id"], canonical(result)))

    def recover(self, run_id: str) -> None:
        rows = self.db.execute("SELECT id,payload FROM attempts WHERE run_id=?", (run_id,)).fetchall()
        with self.db:
            for row in rows:
                payload = json.loads(row["payload"])
                if payload["status"] == "running":
                    payload.update(status="interrupted", error="Process stopped before checkpoint; generation may have occurred.", ended_at=now())
                    self.db.execute("UPDATE attempts SET payload=? WHERE id=?", (canonical(payload), row["id"]))
