import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from Agent import LuciosAgent
from benchmarks.runner import (CENARIOS, achatar_medicoes, executar_amostra, executar_benchmark,
                       estatisticas, main, salvar_relatorios)
from orchestrator import Configuracao, Medicao


class BenchmarkTests(unittest.TestCase):
    def test_todos_cenarios_simulados_e_aquecimentos_separados(self):
        relatorio = executar_benchmark([Configuracao()], list(CENARIOS), 2, 1, True)
        self.assertEqual(len(relatorio["amostras"]), 12)
        self.assertEqual(len(relatorio["aquecimentos"]), 6)
        self.assertTrue(all(a["estado"] == "concluido" for a in relatorio["amostras"]))
        self.assertTrue(all(r["total"]["n"] == 2 for r in relatorio["resumos"]))
        limpeza = next(a for a in relatorio["amostras"] if a["cenario"] == "limpeza")
        self.assertEqual(limpeza["chamadas_modelo"], 0)
        ambigua = next(a for a in relatorio["amostras"] if a["cenario"] == "memoria_ambigua")
        self.assertEqual(ambigua["chamadas_modelo"], 2)
        encerramento = next(a for a in relatorio["amostras"] if a["cenario"] == "encerramento")
        self.assertEqual(encerramento["chamadas_modelo"], 1)
        self.assertIn("persistencia_memoria", [e["etapa"] for e in encerramento["etapas"]])
        self.assertIn("geracao_resumo/inferencia_resumo", [e["etapa"] for e in encerramento["etapas"]])

    def test_relatorios_nao_contem_mensagens_respostas_ou_erros_brutos(self):
        cliente = Mock()
        cliente.chat.side_effect = RuntimeError("SEGREDO_DE_TESTE")
        relatorio = executar_benchmark([Configuracao()], ["conversa"], 1, 0,
                                       fabrica_cliente=lambda config: cliente)
        texto = json.dumps(relatorio, ensure_ascii=False)
        self.assertNotIn("SEGREDO_DE_TESTE", texto)
        self.assertNotIn(CENARIOS["conversa"], texto)
        self.assertEqual(relatorio["amostras"][0]["estado"], "falhou")
        self.assertEqual(relatorio["resumos"][0]["sucessos"], 0)

    def test_memoria_temporaria_independente_do_diretorio_atual(self):
        with patch("benchmarks.runner.LuciosAgent", wraps=LuciosAgent) as agent:
            executar_amostra(Configuracao(), "memoria_busca", True)
        memoria = Path(agent.call_args.kwargs["memory_file"])
        self.assertTrue(memoria.is_absolute())
        self.assertNotEqual(memoria.parent, Path.cwd())
        self.assertFalse(memoria.exists())

    def test_estatisticas_conhecidas_e_p95_por_ordem(self):
        stats = estatisticas([4, 1, 3, 2])
        self.assertEqual(stats["media_s"], 2.5)
        self.assertEqual(stats["mediana_s"], 2.5)
        self.assertEqual(stats["p95_s"], 4)
        self.assertIsNone(estatisticas([]))

    def test_conversao_de_ns_e_tokens_por_segundo(self):
        pai = Medicao("execucao", duracao=4, sucesso=True)
        pai.subetapas.append(Medicao("inferencia", duracao=3, sucesso=True, metricas={
            "load_duration": 1_000_000_000, "eval_duration": 2_000_000_000, "eval_count": 10,
        }))
        linhas = achatar_medicoes([pai])
        self.assertEqual(linhas[0]["exclusivo_s"], 1)
        self.assertEqual(linhas[1]["etapa"], "execucao/inferencia")
        self.assertEqual(linhas[1]["ollama_carga_s"], 1)
        self.assertEqual(linhas[1]["tokens_saida_por_segundo"], 5)

    def test_json_csv_e_ausencia_de_metricas_nao_fornecidas(self):
        relatorio = executar_benchmark([Configuracao()], ["limpeza"], 1, 0, True)
        with TemporaryDirectory() as pasta:
            arquivo_json, arquivo_csv = salvar_relatorios(relatorio, pasta)
            self.assertEqual(json.loads(arquivo_json.read_text(encoding="utf-8"))["modo"], "simulado")
            with arquivo_csv.open(encoding="utf-8-sig", newline="") as arquivo:
                linhas = list(csv.DictReader(arquivo))
            self.assertTrue(linhas)
            self.assertTrue(all(linha["ollama_carga_s"] == "" for linha in linhas))
            outro_json, _ = salvar_relatorios(relatorio, pasta)
            self.assertNotEqual(arquivo_json, outro_json)

    def test_cli_funciona_sem_ollama_no_modo_simulado(self):
        with TemporaryDirectory() as pasta, patch("sys.stdout", new_callable=io.StringIO) as saida:
            code = main(["--simulado", "--cenarios", "conversa", "--repeticoes", "1",
                         "--aquecimentos", "0", "--saida", pasta])
        self.assertEqual(code, 0)
        self.assertIn("SIMULAÇÃO", saida.getvalue())

    def test_parametros_invalidos_nao_iniciam_benchmark(self):
        for repeticoes, aquecimentos in ((0, 0), (1, -1)):
            with self.assertRaises(ValueError):
                executar_benchmark([Configuracao()], ["conversa"], repeticoes, aquecimentos)


if __name__ == "__main__":
    unittest.main()
