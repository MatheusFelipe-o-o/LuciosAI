from pathlib import Path
import shutil
import subprocess
import unittest


class ChatUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node opcional para verificar lógica DOM.")
    def test_fluxos_da_interface(self):
        result = subprocess.run(["node", "tests/test_chat_ui.js"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
