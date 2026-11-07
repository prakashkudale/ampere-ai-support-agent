import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS accounts(email TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT);
                INSERT OR IGNORE INTO accounts VALUES('priya@example.com','running',NULL);
                INSERT OR IGNORE INTO accounts VALUES('rahul@example.com','offline','missing_api_key');
                CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS messages_chat ON messages(conversation_id,id);
                CREATE TABLE IF NOT EXISTS issues(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    category TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, issue_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS processed_requests(conversation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(conversation_id,request_id));
                CREATE TABLE IF NOT EXISTS passages(id INTEGER PRIMARY KEY, url TEXT NOT NULL,
                    title TEXT NOT NULL, text TEXT NOT NULL, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(title, text, content='passages', content_rowid='id');
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self, conversation_id):
        with self.connect() as db:
            row = db.execute("SELECT state FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return json.loads(row[0]) if row else {"email": None, "issue_id": None, "category": None,
                                             "stage": "idle", "rounds": 0, "status": None}

    def save_state(self, conversation_id, state):
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                       (conversation_id, json.dumps(state)))

    def history(self, conversation_id):
        with self.connect() as db:
            rows = db.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12",
                              (conversation_id,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def replay(self, conversation_id, request_id):
        with self.connect() as db:
            row = db.execute("SELECT fingerprint,response FROM processed_requests WHERE conversation_id=? AND request_id=?",
                             (conversation_id, request_id)).fetchone()
        return dict(row) if row else None

    def finish(self, request, state, response, fingerprint):
        from .privacy import SECRET
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                       (request.conversation_id, json.dumps(state)))
            db.executemany("INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)", [
                (request.conversation_id, "user", SECRET.sub("[SECRET]", request.message)),
                (request.conversation_id, "assistant", response.answer)])
            db.execute("INSERT INTO processed_requests VALUES(?,?,?,?)",
                       (request.conversation_id, request.request_id, fingerprint, response.model_dump_json()))

    def new_issue(self, conversation_id, category):
        issue_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO issues(id,conversation_id,category) VALUES(?,?,?)", (issue_id, conversation_id, category))
        return issue_id

    def resolve(self, issue_id):
        with self.connect() as db:
            db.execute("UPDATE issues SET resolved=1 WHERE id=?", (issue_id,))

    def get_agent_status(self, email):
        """Demo lookup only: email is not authentication. Never exposes other rows."""
        with self.connect() as db:
            row = db.execute("SELECT status,reason FROM accounts WHERE email=?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else {"status": "not_found", "reason": None}

    def ticket(self, issue_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tickets WHERE issue_id=?", (issue_id,)).fetchone()
        return dict(row) if row else None

    def latest_ticket(self, conversation_id):
        with self.connect() as db:
            row = db.execute("""SELECT t.* FROM tickets t JOIN issues i ON i.id=t.issue_id
                WHERE i.conversation_id=? ORDER BY t.rowid DESC LIMIT 1""", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def ensure_ticket(self, issue_id, payload):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO tickets(id,issue_id,payload) VALUES(?,?,?)",
                       (str(uuid4()), issue_id, json.dumps(payload)))
        return self.ticket(issue_id)

    def mark_delivery(self, ticket_id, delivered):
        with self.connect() as db:
            db.execute("UPDATE tickets SET status=?, attempts=attempts+1 WHERE id=?",
                       ("delivered" if delivered else "pending", ticket_id))
