import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def initialize(url):
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url[len(prefix):] in ("", ":memory:"):
        raise ValueError("DATABASE_URL must reference a SQLite file")
    path = Path(url[len(prefix):])
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS session_prompts (
                session_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL
            );
        """)
    return path


def check_database(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute("SELECT id FROM messages LIMIT 1").fetchone()


def load_session(path, session_id):
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN")
        prompt = db.execute("SELECT prompt FROM session_prompts WHERE session_id = ?",
                            (session_id,)).fetchone()
        rows = db.execute("""
            SELECT role, content, metadata FROM messages
            WHERE session_id = ? ORDER BY id
        """, (session_id,))
        messages = []
        for role, content, metadata in rows:
            message = {"role": role, "content": content}
            if metadata is not None:
                message["metadata"] = json.loads(metadata)
            messages.append(message)
    return prompt[0] if prompt else None, messages


def save_turn(path, session_id, prompt, message, reply, metadata):
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path)) as db, db:
        if prompt is not None:
            db.execute("""
                INSERT INTO session_prompts VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET prompt = excluded.prompt
            """, (session_id, prompt))
        db.executemany("""
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, [(session_id, "user", message, None, now),
              (session_id, "assistant", reply, json.dumps(metadata), now)])
