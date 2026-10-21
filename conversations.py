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
                context TEXT NOT NULL, updated TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT 'auto')""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}
            if "model" not in columns:
                db.execute("ALTER TABLE conversations ADD COLUMN model TEXT NOT NULL DEFAULT 'auto'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, model="auto"):
        identifier = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("""INSERT INTO conversations
                       (id, title, messages, context, updated, model)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                       (identifier, "Nova conversa", "[]", "[]", now, model))
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

    def delete(self, identifier):
        if not isinstance(identifier, str) or len(identifier) != 32:
            raise ValueError("Conversa não encontrada.")
        with self.connect() as db:
            deleted = db.execute("DELETE FROM conversations WHERE id = ?", (identifier,))
            if deleted.rowcount != 1:
                raise ValueError("Conversa não encontrada.")

    def set_model(self, identifier, model):
        with self.connect() as db:
            changed = db.execute("UPDATE conversations SET model = ? WHERE id = ?",
                                 (model, identifier))
            if changed.rowcount != 1:
                raise ValueError("Conversa não encontrada.")

    def save(self, conversation, context):
        messages = conversation["messages"]
        first = next((m["content"] for m in messages if m["role"] == "user"), "Nova conversa")
        title = " ".join(first.split())[:70]
        with self.connect() as db:
            db.execute("UPDATE conversations SET title=?, messages=?, context=?, updated=? WHERE id=?",
                       (title, json.dumps(messages, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
                        conversation["id"]))
        conversation["title"] = title
