import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class History:
    def __init__(self, url):
        if not url.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL must be a SQLite file URL")
        self.path = Path(url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, system_prompt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_order ON messages(session_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self, sid):
        with self.connect() as db:
            db.execute("BEGIN")
            session = db.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (sid,)).fetchone()
            rows = db.execute("SELECT role,content,metadata FROM messages WHERE session_id=? ORDER BY id", (sid,))
            messages = []
            for role, content, raw in rows:
                item = {"role": role, "content": content}
                if raw:
                    item["metadata"] = json.loads(raw)
                messages.append(item)
        return (session[0] if session else None), messages

    def append(self, sid, system, message, reply, meta):
        stamp = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("""INSERT INTO sessions VALUES (?,?) ON CONFLICT(session_id)
                          DO UPDATE SET system_prompt=excluded.system_prompt""", (sid, system))
            db.executemany("""INSERT INTO messages(session_id,role,content,metadata,created_at)
                              VALUES (?,?,?,?,?)""", [(sid, "user", message, None, stamp),
                                                      (sid, "assistant", reply, json.dumps(meta), stamp)])

