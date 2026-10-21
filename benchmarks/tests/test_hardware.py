import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from benchmarks.hardware import ColetorHardware, ler_gpus, resumir_hardware


class HardwareTests(unittest.TestCase):
    def test_nvidia_csv_e_campos_indisponiveis(self):
        gpus = ler_gpus('0, RTX Exemplo, 81, 3000, 6000, 70, 45.2\n1, "GPU, extra", N/A, N/A, 4000, [Not Supported], N/A')
        self.assertEqual(gpus[0]["vram_percent"], 50)
        self.assertEqual(gpus[0]["uso_percent"], 81)
        self.assertIsNone(gpus[1]["uso_percent"])
        self.assertIsNone(gpus[1]["vram_percent"])
        self.assertEqual(gpus[1]["nome"], "GPU, extra")
        self.assertEqual(ler_gpus("erro do driver"), [])

    def test_primeira_leitura_cpu_nao_e_zero_ficticio(self):
        sistema = Mock()
        sistema.cpu_percent.return_value = 43
        sistema.virtual_memory.return_value = SimpleNamespace(percent=50, total=1024 ** 3, available=512 * 1024 ** 2)
        sistema.Process.return_value.memory_info.return_value = SimpleNamespace(rss=100 * 1024 ** 2)
        coletor = ColetorHardware(ferramenta="", sistema=sistema)
        self.assertIsNone(coletor.coletar()["cpu_percent"])
        segundo = coletor.coletar()
        self.assertEqual(segundo["cpu_percent"], 43)
        self.assertEqual(segundo["ram_usada_mb"], 512)
        self.assertEqual(segundo["processo_ram_mb"], 100)

    def test_subprocesso_fixo_sem_shell_e_falha_sem_zero_inventado(self):
        executar = Mock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 2))
        coletor = ColetorHardware(ferramenta="ferramenta", executar=executar)
        amostra = coletor.coletar()
        self.assertEqual(amostra["gpus"], [])
        self.assertNotIn("shell", executar.call_args.kwargs)
        self.assertEqual(executar.call_args.kwargs["timeout"], 2)

    def test_resumo_preserva_indisponivel(self):
        coletor = ColetorHardware(ferramenta="")
        amostra = coletor.coletar()
        amostra["cpu_percent"] = None
        resumo = resumir_hardware([amostra])
        self.assertIsNone(resumo["cpu_percent"])
        self.assertEqual(resumo["gpus"], [])


if __name__ == "__main__":
    unittest.main()
