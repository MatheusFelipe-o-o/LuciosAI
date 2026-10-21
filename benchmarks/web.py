"""Painel local de benchmark: python -m benchmarks.web e abra 127.0.0.1:8001."""

import argparse
from collections import deque
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from threading import Event, RLock, Thread
import time
from urllib.parse import urlsplit

import ollama

from .runner import CENARIOS, executar_benchmark, salvar_relatorios
from .score import pontuar
from .hardware import ColetorHardware, resumir_hardware
from orchestrator import Configuracao, observar_medicoes


def modelos_locais():
    cliente = ollama.Client(host="http://127.0.0.1:11434", timeout=3)
    try:
        return [modelo.model for modelo in cliente.list().models]
    finally:
        cliente._client.close()


def validar_opcoes(payload, disponiveis):
    def inteiro(nome, padrao, minimo, maximo):
        valor = payload.get(nome, padrao)
        if type(valor) is not int or not minimo <= valor <= maximo:
            raise ValueError(f"{nome}: use um inteiro entre {minimo} e {maximo}.")
        return valor
    simulado = payload.get("simulado", False)
    if type(simulado) is not bool:
        raise ValueError("Modo inválido.")
    modelo = payload.get("modelo", "llama3.2:latest")
    complexo = payload.get("modelo_complexo")
    if complexo == "":
        complexo = None
    if not isinstance(modelo, str) or not modelo.strip() or len(modelo) > 150:
        raise ValueError("Selecione um modelo válido.")
    if complexo is not None and (not isinstance(complexo, str) or not complexo.strip() or len(complexo) > 150):
        raise ValueError("Modelo complexo inválido.")
    if not simulado and (modelo not in disponiveis or (complexo and complexo not in disponiveis)):
        raise ValueError("Selecione somente modelos instalados no Ollama local.")
    cenarios = payload.get("cenarios", list(CENARIOS))
    if (not isinstance(cenarios, list) or not 1 <= len(cenarios) <= len(CENARIOS)
            or any(not isinstance(c, str) or c not in CENARIOS for c in cenarios)
            or len(set(cenarios)) != len(cenarios)):
        raise ValueError("Selecione cenários válidos, sem repetições.")
    config = Configuracao(
        modelo_economico=modelo, modelo_complexo=complexo,
        contexto=inteiro("contexto", 4096, 512, 32768),
        limite_resposta=inteiro("limite_resposta", 128, 32, 2048),
        timeout=inteiro("timeout", 120, 5, 300),
    )
    return config, cenarios, inteiro("repeticoes", 3, 1, 10), inteiro("aquecimentos", 1, 0, 2), simulado


class PainelBenchmark:
    def __init__(self, coletor=None, pasta=None, executor=executar_benchmark, monitorar=True):
        self.lock = RLock()
        self.coletor = coletor or ColetorHardware()
        self.pasta = Path(pasta) if pasta else Path(__file__).resolve().parent / "benchmark_results"
        self.executor = executor
        self.parar = Event()
        self.cancelar = Event()
        self.worker = None
        self.monitor = None
        self.historico = deque(maxlen=120)
        self.hardware_rodada = deque(maxlen=3600)
        self.total_leituras = 0
        self.relatorio = None
        self.arquivos = {}
        self.estado = {"fase": "ocioso", "atual": None, "etapas": {}, "amostras": [],
                       "concluidas": 0, "total": 0, "inicio": None, "duracao_s": 0,
                       "resultado": None, "erro": None}
        if monitorar:
            self.monitor = Thread(target=self._monitorar, daemon=True)
            self.monitor.start()

    def _monitorar(self):
        while not self.parar.is_set():
            inicio = time.perf_counter()
            try:
                self.receber_hardware(self.coletor.coletar())
            except Exception:
                pass
            self.parar.wait(max(0.1, 1 - (time.perf_counter() - inicio)))

    def receber_hardware(self, amostra):
        with self.lock:
            self.historico.append(deepcopy(amostra))
            if self.estado["fase"] in ("executando", "cancelando") and amostra["instante"] >= self.inicio_wall:
                self.hardware_rodada.append(deepcopy(amostra))
                self.total_leituras += 1

    def _progresso(self, modelo, cenario, fase, numero):
        with self.lock:
            self.estado["atual"] = {"modelo": modelo, "cenario": cenario, "fase": fase, "numero": numero}
            self.estado["etapas"] = {}

    def _evento(self, evento):
        with self.lock:
            if evento["fase"] == "modelo":
                if self.estado["atual"] is not None:
                    self.estado["atual"]["modelo_em_uso"] = evento["modelo"]
                return
            etapas = self.estado["etapas"]
            if evento["fase"] == "inicio":
                etapas[evento["etapa"]] = {"etapa": evento["etapa"], "status": "executando",
                                          "inicio": time.perf_counter(), "duracao_s": 0}
            else:
                etapas[evento["etapa"]] = {"etapa": evento["etapa"],
                                          "status": "concluida" if evento["sucesso"] else "falhou",
                                          "duracao_s": evento["duracao"]}

    def _concluir_amostra(self, amostra, fase):
        with self.lock:
            self.estado["concluidas"] += 1
            self.estado["amostras"].append({**deepcopy(amostra), "fase": fase})

    def iniciar(self, opcoes):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise RuntimeError("Já existe uma rodada em execução.")
            config, cenarios, repeticoes, aquecimentos, simulado = opcoes
            self.cancelar = Event()
            self.relatorio, self.arquivos = None, {}
            self.hardware_rodada.clear()
            self.total_leituras = 0
            self.inicio_wall = time.time()
            self.estado = {"fase": "executando", "atual": None, "etapas": {}, "amostras": [],
                           "concluidas": 0, "total": len(cenarios) * (repeticoes + aquecimentos),
                           "inicio": time.perf_counter(), "duracao_s": 0, "resultado": None, "erro": None}
            self.worker = Thread(target=self._executar, args=opcoes, daemon=True)
            self.worker.start()

    def _executar(self, config, cenarios, repeticoes, aquecimentos, simulado):
        try:
            with observar_medicoes(self._evento):
                relatorio = self.executor([config], cenarios, repeticoes, aquecimentos, simulado,
                                           progresso=self._progresso, cancelar=self.cancelar,
                                           ao_concluir=self._concluir_amostra)
            with self.lock:
                hardware = list(self.hardware_rodada)
                truncada = self.total_leituras > len(hardware)
            relatorio["hardware"] = {"intervalo_nominal_s": 1, "amostras": hardware,
                                     "captura_truncada": truncada, "resumo": resumir_hardware(hardware)}
            relatorio["pontuacao"] = pontuar(relatorio)
            arquivos = salvar_relatorios(relatorio, self.pasta)
            with self.lock:
                self.relatorio = relatorio
                self.arquivos = dict(zip(("json", "csv"), arquivos))
                self.estado["fase"] = "cancelado" if relatorio.get("interrompido") else "concluido"
                self.estado["resultado"] = {"pontuacao": relatorio["pontuacao"],
                                            "resumos": relatorio["resumos"],
                                            "hardware": relatorio["hardware"]["resumo"],
                                            "hardware_truncado": truncada,
                                            "modo": relatorio["modo"]}
        except Exception:
            with self.lock:
                self.estado["fase"] = "falhou"
                self.estado["erro"] = "Não foi possível finalizar a rodada. Verifique Ollama e a pasta de relatórios."
        finally:
            with self.lock:
                self.estado["duracao_s"] = time.perf_counter() - self.estado["inicio"]

    def interromper(self):
        with self.lock:
            if self.estado["fase"] in ("executando", "cancelando"):
                self.cancelar.set()
                self.estado["fase"] = "cancelando"

    def snapshot(self):
        with self.lock:
            estado = deepcopy(self.estado)
            ativo = self.worker is not None and self.worker.is_alive()
            if ativo and estado["inicio"] is not None:
                estado["duracao_s"] = time.perf_counter() - estado["inicio"]
            for etapa in estado["etapas"].values():
                if etapa["status"] == "executando":
                    etapa["duracao_s"] = time.perf_counter() - etapa.pop("inicio")
            estado.pop("inicio", None)
            estado.update(ativo=ativo, historico_hardware=list(self.historico),
                          hardware=self.historico[-1] if self.historico else None)
            return estado

    def fechar(self):
        self.parar.set()
        self.interromper()
        if self.monitor:
            self.monitor.join(timeout=3)


class BenchmarkHandler(BaseHTTPRequestHandler):
    def enviar(self, conteudo, status=200, tipo="application/json; charset=utf-8", download=None):
        dados = json.dumps(conteudo, ensure_ascii=False, allow_nan=False).encode() if isinstance(conteudo, dict) else conteudo
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            self.enviar({"error": "Host local inválido."}, 403)
            return
        rota = urlsplit(self.path).path
        if rota == "/":
            html = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
            self.enviar(html.replace("__TOKEN__", self.server.token).encode(), tipo="text/html; charset=utf-8")
        elif rota == "/api/state":
            self.enviar(self.server.painel.snapshot())
        elif rota == "/api/models":
            try:
                self.enviar({"modelos": modelos_locais(), "disponivel": True})
            except Exception:
                self.enviar({"modelos": [], "disponivel": False})
        elif rota in ("/api/report", "/api/csv"):
            extensao = "json" if rota == "/api/report" else "csv"
            with self.server.painel.lock:
                arquivo = self.server.painel.arquivos.get(extensao)
            if arquivo is None:
                self.enviar({"error": "Nenhum relatório concluído."}, 404)
            else:
                self.enviar(arquivo.read_bytes(), tipo="application/json" if extensao == "json" else "text/csv; charset=utf-8",
                            download=arquivo.name)
        else:
            self.enviar({"error": "Rota não encontrada."}, 404)

    def do_POST(self):
        self.connection.settimeout(5)
        origens = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        hosts = {origem.removeprefix("http://") for origem in origens}
        if (self.headers.get("Host") not in hosts
                or self.headers.get("Origin") not in origens | {None}
                or not secrets.compare_digest(self.headers.get("X-Lucios-Token", ""), self.server.token)):
            tamanho = self.headers.get("Content-Length", "0")
            if tamanho.isdigit() and 0 < int(tamanho) <= 16384:
                try:
                    self.rfile.read(int(tamanho))
                except OSError:
                    pass
            self.enviar({"error": "Solicitação não autorizada para este painel local."}, 403)
            return
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 < tamanho <= 16384 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Envie um objeto JSON válido.")
            payload = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("O JSON deve ser um objeto.")
            if self.path == "/api/start":
                disponiveis = [] if payload.get("simulado") is True else modelos_locais()
                opcoes = validar_opcoes(payload, disponiveis)
                self.server.painel.iniciar(opcoes)
            elif self.path == "/api/cancel":
                self.server.painel.interromper()
            else:
                self.enviar({"error": "Rota não encontrada."}, 404)
                return
        except ValueError as erro:
            self.enviar({"error": str(erro)}, 400)
            return
        except RuntimeError as erro:
            self.enviar({"error": str(erro)}, 409)
            return
        except Exception:
            self.enviar({"error": "Ollama local indisponível. Inicie o serviço ou use simulação."}, 503)
            return
        self.enviar({"ok": True})

    def log_message(self, format, *args):
        return


def criar_servidor(porta=8001, painel=None):
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), BenchmarkHandler)
    servidor.painel = painel or PainelBenchmark()
    servidor.token = secrets.token_urlsafe(24)
    return servidor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--porta", type=int, default=8001)
    args = parser.parse_args()
    servidor = criar_servidor(args.porta)
    print(f"Painel de desempenho: http://127.0.0.1:{servidor.server_port}", flush=True)
    print("Ctrl+C para encerrar. Relatórios permanecem locais.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        servidor.painel.fechar()


if __name__ == "__main__":
    main()
