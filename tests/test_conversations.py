from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from conversations import ConversationStore


class ConversationTests(unittest.TestCase):
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
