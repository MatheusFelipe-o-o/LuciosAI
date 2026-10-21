"""Fluxo finito de tarefas. Não executa código, comandos ou ferramentas externas."""

from dataclasses import dataclass, field, replace
from contextlib import contextmanager
from enum import Enum
import math
import os
from threading import Event
import time
from typing import Callable
import unicodedata


class Estado(str, Enum):
    RECEBIDO = "recebido"
    VALIDANDO = "validando"
    EXECUTANDO = "executando"
    VERIFICANDO = "verificando"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"


@dataclass(frozen=True)
class Configuracao:
    modelo_economico: str = "llama3.2"
    modelo_complexo: str | None = None
    contexto: int = 4096
    limite_resposta: int = 1024
    timeout: float = 120
    limite_chamadas: int = 2
    limite_entrada: int = 16000

    def __post_init__(self):
        for nome in (self.modelo_economico, self.modelo_complexo):
            if nome is not None and (not isinstance(nome, str) or not nome.strip()):
                raise ValueError("O nome do modelo deve ser uma string não vazia.")
        if self.modelo_economico is None:
            raise ValueError("Um modelo econômico é obrigatório.")
        for campo in ("contexto", "limite_resposta", "limite_chamadas", "limite_entrada"):
            valor = getattr(self, campo)
            if type(valor) is not int or valor <= 0:
                raise ValueError(f"{campo} deve ser um inteiro positivo.")
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool):
            raise ValueError("timeout deve ser um número positivo e finito.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout deve ser um número positivo e finito.")

    @classmethod
    def do_ambiente(cls, modelo: str | None = None):
        return cls(
            modelo_economico=modelo if modelo is not None else os.getenv("LUCIOS_MODELO", "llama3.2"),
            modelo_complexo=os.getenv("LUCIOS_MODELO_COMPLEXO") or None,
            contexto=int(os.getenv("LUCIOS_CONTEXTO", "4096")),
            limite_resposta=int(os.getenv("LUCIOS_LIMITE_RESPOSTA", "1024")),
            timeout=float(os.getenv("LUCIOS_TIMEOUT", "120")),
        )


@dataclass(frozen=True)
class Decisao:
    estrategia: str
    complexidade: str
    modelo: str | None
    motivo: str
    risco: str = "sem_execucao_externa"


@dataclass
class Medicao:
    etapa: str
    duracao: float = 0
    sucesso: bool = False
    subetapas: list["Medicao"] = field(default_factory=list)
    metricas: dict[str, float | int] = field(default_factory=dict)

    @property
    def exclusiva(self):
        """Tempo próprio, descontando somente filhos imediatos."""
        return max(0, self.duracao - sum(filho.duracao for filho in self.subetapas))


@contextmanager
def medir_etapa(medicoes, nome, relogio=time.perf_counter):
    medicao = Medicao(nome)
    medicoes.append(medicao)
    inicio = relogio()
    try:
        yield medicao
        medicao.sucesso = True
    finally:
        medicao.duracao = max(0, relogio() - inicio)


def _metricas_ollama(resposta):
    """Captura apenas contadores numéricos permitidos, nunca conteúdo do modelo."""
    metricas = {}
    for nome in ("total_duration", "load_duration", "prompt_eval_duration",
                 "eval_duration", "prompt_eval_count", "eval_count"):
        valor = resposta.get(nome) if isinstance(resposta, dict) else getattr(resposta, nome, None)
        if type(valor) in (int, float) and math.isfinite(valor) and valor >= 0:
            metricas[nome] = valor
    return metricas


@dataclass
class Resultado:
    estados: list[Estado] = field(default_factory=lambda: [Estado.RECEBIDO])
    decisao: Decisao | None = None
    resposta: str = ""
    erro: str | None = None
    chamadas_modelo: int = 0
    duracao: float = 0
    duracao_chat: float = 0
    medicoes: list[Medicao] = field(default_factory=list)

    @property
    def estado(self):
        return self.estados[-1]

    def transicionar(self, destino: Estado):
        permitidas = {
            Estado.RECEBIDO: {Estado.VALIDANDO},
            Estado.VALIDANDO: {Estado.EXECUTANDO, Estado.FALHOU, Estado.CANCELADO},
            Estado.EXECUTANDO: {Estado.VERIFICANDO, Estado.FALHOU, Estado.CANCELADO},
            Estado.VERIFICANDO: {Estado.CONCLUIDO, Estado.FALHOU, Estado.CANCELADO},
        }
        if destino not in permitidas.get(self.estado, set()):
            raise ValueError(f"Transição inválida: {self.estado.value} -> {destino.value}")
        self.estados.append(destino)


class ExecucaoCancelada(Exception):
    pass


class ContextoExecucao:
    def __init__(self, config, resultado, chamar_modelo, cancelar, relogio):
        self.config = config
        self.resultado = resultado
        self._chamar_modelo = chamar_modelo
        self._cancelar = cancelar
        self._relogio = relogio
        self.inicio = relogio()
        self._pilha_medicoes = []

    @contextmanager
    def medir(self, nome):
        destino = self._pilha_medicoes[-1].subetapas if self._pilha_medicoes else self.resultado.medicoes
        with medir_etapa(destino, nome, self._relogio) as medicao:
            self._pilha_medicoes.append(medicao)
            try:
                yield medicao
            finally:
                self._pilha_medicoes.pop()

    def verificar_limites(self):
        if self._cancelar is not None and self._cancelar.is_set():
            raise ExecucaoCancelada("Tarefa cancelada.")
        if self._relogio() - self.inicio >= self.config.timeout:
            raise TimeoutError("A tarefa excedeu o orçamento de tempo.")

    def chamar_modelo(self, etapa="inferencia", **parametros):
        self.verificar_limites()
        if self.resultado.chamadas_modelo >= self.config.limite_chamadas:
            raise RuntimeError("Limite de chamadas ao modelo atingido.")
        self.resultado.chamadas_modelo += 1
        with self.medir(etapa) as medicao:
            resposta = self._chamar_modelo(**parametros)
            medicao.metricas = _metricas_ollama(resposta)
            self.verificar_limites()
        return resposta


def _normalizar(texto):
    return "".join(
        letra for letra in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(letra)
    )


def _nome_modelo(nome):
    return nome if ":" in nome else nome + ":latest"


class Orquestrador:
    def __init__(self, config: Configuracao, chamar_modelo: Callable,
                 listar_modelos: Callable, relogio: Callable = time.perf_counter):
        self.config = config
        self._chamar_modelo = chamar_modelo
        self._listar_modelos = listar_modelos
        self._relogio = relogio

    def classificar(self, texto: str) -> Decisao:
        normalizado = _normalizar(texto)
        if normalizado == "limpar":
            return Decisao("limpar", "simples", None, "Comando local existente.")
        sinais = ("planeje", "plano detalhado", "analise detalhada", "analise profunda",
                  "compare alternativas", "passo a passo", "arquitetura", "investigue")
        complexa = len(texto) > 2000 or any(sinal in normalizado for sinal in sinais)
        return Decisao(
            "conversar", "complexa" if complexa else "intermediaria",
            self.config.modelo_economico,
            "Heurística de planejamento/análise." if complexa else "Conversa com modelo econômico.",
        )

    def _selecionar_modelo(self, decisao, contexto):
        if decisao.complexidade != "complexa" or not self.config.modelo_complexo:
            if decisao.complexidade == "complexa":
                return replace(decisao, motivo="Fallback: modelo complexo não configurado.")
            return decisao
        contexto.verificar_limites()
        try:
            with contexto.medir("catalogo_modelos"):
                disponiveis = {_nome_modelo(nome) for nome in self._listar_modelos()}
        except Exception:
            contexto.verificar_limites()
            return replace(decisao, motivo="Fallback: catálogo local indisponível.")
        contexto.verificar_limites()
        if _nome_modelo(self.config.modelo_complexo) in disponiveis:
            return replace(decisao, modelo=self.config.modelo_complexo,
                           motivo="Modelo complexo configurado e instalado.")
        return replace(decisao, motivo="Fallback: modelo complexo não instalado.")

    def executar(self, pedido, responder: Callable, limpar: Callable,
                 cancelar: Event | None = None) -> Resultado:
        resultado = Resultado()
        contexto = ContextoExecucao(self.config, resultado, self._chamar_modelo,
                                   cancelar, self._relogio)
        resultado.transicionar(Estado.VALIDANDO)
        try:
            with contexto.medir("validacao"):
                contexto.verificar_limites()
                if not isinstance(pedido, str) or not pedido.strip():
                    raise ValueError("A mensagem deve ser um texto não vazio.")
                if len(pedido) > self.config.limite_entrada:
                    raise ValueError(f"Mensagem excede {self.config.limite_entrada} caracteres.")
                texto = pedido.strip()
            with contexto.medir("classificacao_tarefa"):
                decisao = self.classificar(texto)
            with contexto.medir("selecao_modelo"):
                resultado.decisao = self._selecionar_modelo(decisao, contexto)
            contexto.verificar_limites()
            resultado.transicionar(Estado.EXECUTANDO)
            with contexto.medir("execucao"):
                if resultado.decisao.estrategia == "limpar":
                    with contexto.medir("limpeza_conversa"):
                        resposta = limpar()
                else:
                    resposta = responder(texto, resultado.decisao.modelo, contexto)
            resultado.transicionar(Estado.VERIFICANDO)
            with contexto.medir("verificacao"):
                contexto.verificar_limites()
                if not isinstance(resposta, str) or not resposta.strip():
                    raise ValueError("O modelo ou a operação não retornou uma resposta textual válida.")
                resultado.resposta = resposta
            resultado.transicionar(Estado.CONCLUIDO)
        except ExecucaoCancelada as erro:
            resultado.erro = str(erro)
            resultado.transicionar(Estado.CANCELADO)
        except Exception as erro:
            resultado.erro = str(erro)
            resultado.transicionar(Estado.FALHOU)
        resultado.duracao = max(0, self._relogio() - contexto.inicio)
        return resultado
