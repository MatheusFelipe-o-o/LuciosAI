from pathlib import Path
import shutil
import subprocess
import unittest


class DashboardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node é opcional, usado somente no teste da interface.")
    def test_logica_dom_e_javascript(self):
        repo = Path(__file__).resolve().parents[1]
        resultado = subprocess.run(["node", "tests/test_dashboard.js"], cwd=repo,
                                    capture_output=True, timeout=10)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
