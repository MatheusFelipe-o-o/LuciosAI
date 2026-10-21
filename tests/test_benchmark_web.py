from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

from benchmark import executar_benchmark
from benchmark_score import pontuar
from benchmark_web import PainelBenchmark, criar_servidor, validar_opcoes
from orchestrator import Configuracao


class ScoreTests(unittest.TestCase):
    def relatorio(self):
        relatorio = executar_benchmark([Configuracao()], ["conversa"], 3, 0, True)
        relatorio["modo"] = "ollama_real"
        for amostra in relatorio["amostras"]:
            amostra["total_s"] = 1
        return relatorio

    def test_melhor_caso_conhecido_e_falhas_penalizadas(self):
        r = self.relatorio()
        self.assertEqual(pontuar(r)["nota"], 1000)
        r["amostras"][0]["estado"] = "falhou"
        self.assertEqual(pontuar(r)["nota"], 667)
        for a in r["amostras"]:
            a["estado"] = "falhou"
        self.assertEqual(pontuar(r)["nota"], 0)

    def test_sem_nota_simulada_ou_interrompida(self):
        r = self.relatorio()
        r["modo"] = "simulado"
        self.assertIsNone(pontuar(r)["nota"])
        r["modo"], r["interrompido"] = "ollama_real", True
        self.assertIsNone(pontuar(r)["nota"])

    def test_amostra_unica_provisoria_e_perfil_comparavel(self):
        r = self.relatorio()
        outro = deepcopy(r)
        outro["configuracoes"][0]["modelo_economico"] = "outro"
        self.assertEqual(pontuar(r)["perfil"], pontuar(outro)["perfil"])
        r["amostras"] = r["amostras"][:1]
        r["amostras"][0]["total_s"] = 4
        self.assertEqual(pontuar(r)["nota"], 500)
        self.assertTrue(pontuar(r)["provisorio"])


class PainelTests(unittest.TestCase):
    def test_modelo_em_uso_atualiza_sem_inventar_etapa(self):
        painel = PainelBenchmark(monitorar=False)
        painel._progresso("economico", "complexa", "medicao", 1)
        painel._evento({"fase": "modelo", "modelo": "complexo", "etapa": "execucao/inferencia_resposta"})
        self.assertEqual(painel.snapshot()["atual"]["modelo_em_uso"], "complexo")
        self.assertEqual(painel.snapshot()["etapas"], {})
        painel.fechar()

    def test_limites_e_modelos_instalados(self):
        for payload in ({"modelo": "ausente"}, {"repeticoes": True}, {"cenarios": ["conversa", "conversa"]},
                        {"contexto": 999999}, {"simulado": "false"}, {"modelo_complexo": False}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validar_opcoes(payload, ["llama3.2:latest"])
        opcoes = validar_opcoes({"simulado": True, "repeticoes": 1}, [])
        self.assertEqual(opcoes[2], 1)

    def test_rodada_unica_cancelamento_e_relatorio_parcial(self):
        gate = Event()
        def executor(*args, **kwargs):
            gate.wait(timeout=3)
            return executar_benchmark(*args, **kwargs)
        with TemporaryDirectory() as pasta:
            painel = PainelBenchmark(pasta=pasta, monitorar=False, executor=executor)
            opcoes = validar_opcoes({"simulado": True, "repeticoes": 1, "aquecimentos": 0}, [])
            painel.iniciar(opcoes)
            with self.assertRaises(RuntimeError):
                painel.iniciar(opcoes)
            painel.interromper()
            gate.set()
            painel.worker.join(timeout=4)
            self.assertEqual(painel.snapshot()["fase"], "cancelado")
            self.assertIsNone(painel.relatorio["pontuacao"]["nota"])
            self.assertEqual(len(list(Path(pasta).glob("*.json"))), 1)
            painel.fechar()

    def test_http_autorizacao_start_estado_e_download(self):
        with TemporaryDirectory() as pasta:
            painel = PainelBenchmark(pasta=pasta, monitorar=False)
            servidor = criar_servidor(0, painel)
            thread = Thread(target=servidor.serve_forever, daemon=True)
            thread.start()
            try:
                def request(method, rota, body=None, token=True):
                    conn = HTTPConnection("127.0.0.1", servidor.server_port, timeout=5)
                    try:
                        headers = {"Content-Type": "application/json"}
                        if token:
                            headers["X-Lucios-Token"] = servidor.token
                        conn.request(method, rota, json.dumps(body or {}) if method == "POST" else None, headers)
                        resposta = conn.getresponse()
                        return resposta.status, resposta.read()
                    finally:
                        conn.close()
                self.assertEqual(request("POST", "/api/start", token=False)[0], 403)
                payload = {"simulado": True, "cenarios": ["limpeza"], "repeticoes": 1, "aquecimentos": 0}
                self.assertEqual(request("POST", "/api/start", payload)[0], 200)
                painel.worker.join(timeout=4)
                status, body = request("GET", "/api/state")
                estado = json.loads(body)
                self.assertEqual(status, 200)
                self.assertEqual(estado["fase"], "concluido")
                self.assertIsNone(estado["resultado"]["pontuacao"]["nota"])
                self.assertEqual(request("GET", "/api/report")[0], 200)
                self.assertEqual(request("GET", "/api/csv")[0], 200)
            finally:
                servidor.shutdown()
                servidor.server_close()
                painel.fechar()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
