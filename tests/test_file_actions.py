from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from file_actions import FileActions, FileActionError


class FileActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.actions = FileActions(self.root)

    def plan(self, operation, source, **extra):
        return self.actions.prepare({
            "operation": operation, "source": source,
            "interpretation": "Entendi a ação pedida.", **extra})

    def test_criar_editar_mover_e_lixeira(self):
        create = self.plan("create", "nota.md", content="Antes\n")
        self.assertFalse((self.root / "nota.md").exists())
        self.actions.execute(create)
        edit = self.plan("edit", "nota.md", content="Depois\n")
        self.assertIn("-Antes", edit.preview)
        self.actions.execute(edit)
        self.assertEqual((self.root / "nota.md").read_text(), "Depois\n")
        move = self.plan("move", "nota.md", target="novo.md")
        self.actions.execute(move)
        self.assertFalse((self.root / "nota.md").exists())
        result = self.actions.execute(self.plan("delete", "novo.md"))
        self.assertIn(".lucios_trash", result)
        self.assertFalse((self.root / "novo.md").exists())
        self.assertEqual(len(list((self.root / ".lucios_trash").iterdir())), 1)

    def test_mudanca_apos_previa_recusa_execucao(self):
        path = self.root / "a.md"
        path.write_text("um")
        proposal = self.plan("edit", "a.md", content="dois")
        path.write_text("alterado")
        with self.assertRaisesRegex(FileActionError, "mudaram"):
            self.actions.execute(proposal)
        self.assertEqual(path.read_text(), "alterado")

    def test_listar_buscar_ler_e_copiar(self):
        (self.root / "nota.md").write_text("Olá", encoding="utf-8")
        self.assertIn("nota.md", self.actions.execute(self.plan("list", ".")))
        found = self.actions.execute(self.plan("search", ".", query="not"))
        self.assertIn("1 arquivo(s)", found)
        self.assertIn("nota.md", found)
        self.assertEqual(self.actions.execute(self.plan("read", "nota.md")), "Olá")
        self.actions.execute(self.plan("copy", "nota.md", target="copia.md"))
        self.assertEqual((self.root / "copia.md").read_text(encoding="utf-8"), "Olá")

    def test_caminho_fora_da_raiz_e_sobrescrita_recusados(self):
        with self.assertRaises(FileActionError):
            self.plan("read", "../fora.txt")
        with self.assertRaises(FileActionError):
            self.plan("read", str(self.root / "fora.txt"))
        (self.root / "a.txt").write_text("a")
        (self.root / "b.txt").write_text("b")
        with self.assertRaisesRegex(FileActionError, "já existe"):
            self.plan("copy", "a.txt", target="b.txt")
        outside = self.root.parent / "outside-file-actions.txt"
        try:
            (self.root / "link.txt").symlink_to(outside)
        except OSError:
            return
        with self.assertRaises(FileActionError):
            self.plan("read", "link.txt")
