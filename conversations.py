"""Histórico privado da interface web, independente da memória semântica do agente."""

from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class ConversationStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, messages TEXT NOT NULL,
                context TEXT NOT NULL, updated TEXT NOT NULL)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self):
        identifier = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                       (identifier, "Nova conversa", "[]", "[]", now))
        return self.get(identifier)

    def get(self, identifier):
        if not isinstance(identifier, str) or len(identifier) != 32:
            raise ValueError("Conversa não encontrada.")
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Conversa não encontrada.")
        return {**dict(row), "messages": json.loads(row["messages"]),
                "context": json.loads(row["context"])}

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, title, updated FROM conversations ORDER BY updated DESC")]

    def save(self, conversation, context):
        messages = conversation["messages"]
        first = next((m["content"] for m in messages if m["role"] == "user"), "Nova conversa")
        title = " ".join(first.split())[:70]
        with self.connect() as db:
            db.execute("UPDATE conversations SET title=?, messages=?, context=?, updated=? WHERE id=?",
                       (title, json.dumps(messages, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
                        conversation["id"]))
