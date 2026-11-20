from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from conversations import ConversationStore


class ConversationTests(unittest.TestCase):
    def test_banco_antigo_ganha_modelo_automatico_sem_perder_mensagens(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.db"
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("""CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                               messages TEXT NOT NULL, context TEXT NOT NULL, updated TEXT NOT NULL)""")
                    db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                               ("a" * 32, "Antiga", '[{"role":"user","content":"Oi"}]', "[]", "2026-01-01"))
            finally:
                db.close()
            store = ConversationStore(path)
            self.assertEqual(store.get("a" * 32)["model"], "auto")
            self.assertEqual(store.get("a" * 32)["messages"][0]["content"], "Oi")

    def test_exclusao_persiste_e_preserva_outros(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.db"
            store = ConversationStore(path)
            a, b = store.create(), store.create()
            store.delete(a["id"])
            reopened = ConversationStore(path)
            with self.assertRaises(ValueError):
                reopened.get(a["id"])
            self.assertEqual(reopened.get(b["id"])["id"], b["id"])

    def test_reabre_banco_sem_perder_conversa_e_contexto(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "private" / "history.db"
            store = ConversationStore(path)
            item = store.create()
            item["messages"] = [{"role": "user", "content": "Título com acentuação"}]
            context = item["messages"] + [{"role": "assistant", "content": "Olá"}]
            store.save(item, context)
            reopened = ConversationStore(path)
            self.assertEqual(reopened.get(item["id"])["context"], context)
            self.assertEqual(reopened.list()[0]["title"], "Título com acentuação")
            with self.assertRaises(ValueError):
                reopened.get("' OR 1=1 --")

    def test_banco_com_esforco_antigo_preserva_conversa_e_remove_coluna(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.db"
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("""CREATE TABLE conversations (id TEXT PRIMARY KEY,
                               title TEXT NOT NULL, messages TEXT NOT NULL, context TEXT NOT NULL,
                               updated TEXT NOT NULL, model TEXT NOT NULL, effort TEXT NOT NULL)""")
                    db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
                               ("a" * 32, "Antiga", '[{"role":"user","content":"Oi"}]',
                                "[]", "2026-01-01", "qwen3:8b", "high"))
            finally:
                db.close()
            store = ConversationStore(path)
            item = store.get("a" * 32)
            self.assertEqual(item["messages"][0]["content"], "Oi")
            self.assertEqual(item["model"], "qwen3:8b")
            self.assertNotIn("effort", item)
            with store.connect() as db:
                self.assertNotIn("effort", {row["name"] for row in
                                           db.execute("PRAGMA table_info(conversations)")})
            self.assertEqual(store.create()["model"], "auto")
