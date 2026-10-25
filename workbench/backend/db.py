"""SQLite persistence for jobs, artifacts and events."""
import sqlite3
import threading
from pathlib import Path

from . import util

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  params_json TEXT NOT NULL,
  argv_json TEXT,
  cwd TEXT,
  status TEXT NOT NULL,
  quality_verdict TEXT NOT NULL DEFAULT 'NOT_EVALUATED',
  exit_code INTEGER,
  created_at TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT,
  timeout_s INTEGER,
  run_dir TEXT,
  log_path TEXT,
  pid INTEGER,
  error TEXT,
  result_json TEXT,
  resources_json TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  kind TEXT,
  path TEXT NOT NULL,
  sha256 TEXT,
  size INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_id);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql, params=()):
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def log_event(self, kind: str, payload: dict):
        import json
        self.execute("INSERT INTO events(ts, kind, payload_json) VALUES(?,?,?)",
                     (util.now_local(), kind, json.dumps(payload, ensure_ascii=False)))

    def close(self):
        with self._lock:
            self._conn.close()
