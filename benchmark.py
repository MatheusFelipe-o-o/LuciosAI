"""Benchmark local com dados sintéticos; relatórios não contêm conversas."""

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
import csv
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
import platform
import statistics
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import ollama

from Agent import LuciosAgent
from orchestrator import Configuracao, _metricas_ollama, medir_etapa


CENARIOS = {
    "limpeza": "limpar",
    "conversa": "Responda brevemente: o que é uma variável em Python?",
    "memoria_busca": "Lembra sobre projeto exemplo",
    "memoria_ambigua": "Como funciona sua memória? Responda brevemente.",
    "complexa": "Planeje em três passos a arquitetura de um aplicativo de notas local.",
    "encerramento": None,
}


class ClienteSimulado:
    """Valida o benchmark offline; não simula velocidade ou métricas de um LLM."""

    def __init__(self, modelos):
        self.modelos = modelos

    def list(self):
        return {"models": [{"model": modelo} for modelo in self.modelos]}

    def chat(self, **kwargs):
        if kwargs.get("format"):
            content = json.dumps({"acao": "nenhuma", "consulta": ""})
        elif len(kwargs.get("messages", [])) == 1:
            content = json.dumps({
                "titulo": "Exemplo sintético", "contexto": "projeto exemplo",
                "resumo": "Foi discutida uma tarefa fictícia.",
                "pontos_aprendidos": [], "pontos_desenvolvidos": [],
            })
        else:
            content = "Resposta sintética para verificar o fluxo."
        return {"message": {"content": content}}


def achatar_medicoes(medicoes, prefixo=""):
    linhas = []
    for medicao in medicoes:
        caminho = f"{prefixo}/{medicao.etapa}" if prefixo else medicao.etapa
        metricas = medicao.metricas
        linha = {
            "etapa": caminho, "inclusivo_s": medicao.duracao,
            "exclusivo_s": medicao.exclusiva, "sucesso": medicao.sucesso,
        }
        for original, destino in (
            ("total_duration", "ollama_total_s"), ("load_duration", "ollama_carga_s"),
            ("prompt_eval_duration", "ollama_prompt_s"), ("eval_duration", "ollama_geracao_s"),
        ):
            if original in metricas:
                linha[destino] = metricas[original] / 1_000_000_000
        for original, destino in (("prompt_eval_count", "tokens_entrada"), ("eval_count", "tokens_saida")):
            if original in metricas:
                linha[destino] = metricas[original]
        if metricas.get("eval_duration", 0) > 0 and "eval_count" in metricas:
            linha["tokens_saida_por_segundo"] = metricas["eval_count"] / (metricas["eval_duration"] / 1e9)
        linhas.append(linha)
        linhas.extend(achatar_medicoes(medicao.subetapas, caminho))
    return linhas


def estatisticas(valores):
    ordenados = sorted(valores)
    if not ordenados:
        return None
    return {
        "n": len(ordenados), "media_s": statistics.mean(ordenados),
        "mediana_s": statistics.median(ordenados),
        "p95_s": ordenados[math.ceil(0.95 * len(ordenados)) - 1],
        "min_s": ordenados[0], "max_s": ordenados[-1],
    }


def resumir(amostras):
    grupos = defaultdict(list)
    for amostra in amostras:
        grupos[(amostra["modelo_configurado"], amostra["cenario"])].append(amostra)
    resumos = []
    for (modelo, cenario), grupo in grupos.items():
        etapas = defaultdict(list)
        for amostra in grupo:
            for etapa in amostra["etapas"]:
                etapas[etapa["etapa"]].append(etapa)
        resumos.append({
            "modelo_configurado": modelo, "cenario": cenario,
            "sucessos": sum(a["estado"] == "concluido" for a in grupo),
            "total": estatisticas([a["total_s"] for a in grupo]),
            "etapas": [{
                "etapa": nome, "sucessos": sum(e["sucesso"] for e in valores),
                "inclusivo": estatisticas([e["inclusivo_s"] for e in valores]),
                "exclusivo": estatisticas([e["exclusivo_s"] for e in valores]),
            } for nome, valores in etapas.items()],
        })
    return resumos


def executar_amostra(config, cenario, simulado=False, fabrica_cliente=None):
    """Isola memória e conversa; preparação do cenário não entra no tempo do pedido."""
    modelos = [config.modelo_economico]
    if config.modelo_complexo:
        modelos.append(config.modelo_complexo)
    cliente = fabrica_cliente(config) if fabrica_cliente else (
        ClienteSimulado(modelos) if simulado else ollama.Client(
            host="http://127.0.0.1:11434", timeout=config.timeout
        )
    )
    try:
        with TemporaryDirectory(prefix="lucios-benchmark-") as temporario:
            agent = LuciosAgent(configuracao=config, cliente=cliente,
                                memory_file=str(Path(temporario) / "memoria_lucios.txt"))
            agent.memory_manager.salvar_memoria({
                "titulo": "Projeto exemplo", "contexto": "projeto exemplo notas",
                "resumo": "Criar um aplicativo fictício de notas local.",
                "data": "01/01/2000", "hora": "00:00:00",
            })
            chamadas_resumo = 0
            def gerar_resumo(**kwargs):
                nonlocal chamadas_resumo
                chamadas_resumo += 1
                # O resumo mantém seu código atual; a sonda só envolve o transporte.
                with medir_etapa(agent.medicoes_encerramento[-1].subetapas, "inferencia_resumo") as medicao:
                    resposta = cliente.chat(**kwargs)
                    medicao.metricas = _metricas_ollama(resposta)
                    return resposta

            if cenario == "encerramento":
                agent.conversa = [
                    {"role": "user", "content": "Vamos criar um aplicativo de notas de exemplo."},
                    {"role": "assistant", "content": "Começaremos por salvar notas localmente."},
                ]
                with patch("memory.ollama.chat", gerar_resumo), redirect_stdout(io.StringIO()):
                    inicio = time.perf_counter()
                    agent.end_conversation()
                    total = time.perf_counter() - inicio
                estado, medicoes = agent.estado_encerramento, agent.medicoes_encerramento
                selecionado, estrategia, chamadas = config.modelo_economico, "encerrar", chamadas_resumo
                duracao_orquestrador = None
            else:
                inicio = time.perf_counter()
                agent.chat(CENARIOS[cenario])
                total = time.perf_counter() - inicio
                resultado = agent.ultimo_resultado
                estado, medicoes = resultado.estado.value, resultado.medicoes
                selecionado = resultado.decisao.modelo if resultado.decisao else None
                estrategia = resultado.decisao.estrategia if resultado.decisao else None
                chamadas, duracao_orquestrador = resultado.chamadas_modelo, resultado.duracao
            etapas = achatar_medicoes(medicoes)
            # O restante é overhead do adaptador/cronômetro, não uma etapa inventada.
            nao_atribuido = max(0, total - sum(m.duracao for m in medicoes))
            return {
                "cenario": cenario, "modelo_configurado": config.modelo_economico,
                "modelo_selecionado": selecionado, "estrategia": estrategia,
                "estado": estado, "chamadas_modelo": chamadas, "total_s": total,
                "orquestrador_s": duracao_orquestrador, "nao_atribuido_s": nao_atribuido,
                "etapas": etapas,
            }
    finally:
        # O cliente Ollama atual não expõe close público; fecha seu transporte no executor isolado.
        if isinstance(cliente, ollama.Client):
            cliente._client.close()


def executar_benchmark(configuracoes, cenarios, repeticoes=3, aquecimentos=1,
                       simulado=False, fabrica_cliente=None, progresso=None):
    if repeticoes <= 0 or aquecimentos < 0:
        raise ValueError("Repetições devem ser positivas e aquecimentos não negativos.")
    if not configuracoes or not cenarios or any(c not in CENARIOS for c in cenarios):
        raise ValueError("Selecione configurações e cenários conhecidos.")
    amostras, aquecimento = [], []
    for config in configuracoes:
        for cenario in cenarios:
            for indice in range(aquecimentos + repeticoes):
                if progresso is not None:
                    fase = "aquecimento" if indice < aquecimentos else "medicao"
                    numero = indice + 1 if indice < aquecimentos else indice - aquecimentos + 1
                    progresso(config.modelo_economico, cenario, fase, numero)
                amostra = executar_amostra(config, cenario, simulado, fabrica_cliente)
                amostra["repeticao"] = indice + 1 if indice < aquecimentos else indice - aquecimentos + 1
                destino = aquecimento if indice < aquecimentos else amostras
                destino.append(amostra)
    return {
        "schema_version": 1, "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "modo": "simulado" if simulado else "ollama_real",
        "ambiente": {"python": platform.python_version(), "sistema": platform.system(),
                     "arquitetura": platform.machine()},
        "configuracoes": [asdict(config) for config in configuracoes],
        "repeticoes": repeticoes, "aquecimentos_por_cenario": aquecimentos,
        "aquecimentos": aquecimento, "amostras": amostras, "resumos": resumir(amostras),
    }


def salvar_relatorios(relatorio, pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = "benchmark_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    arquivo_json, arquivo_csv = pasta / (nome + ".json"), pasta / (nome + ".csv")
    with arquivo_json.open("x", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2, allow_nan=False)
    campos = ["modelo_configurado", "modelo_selecionado", "cenario", "repeticao", "estado",
              "chamadas_modelo", "total_s", "etapa", "inclusivo_s", "exclusivo_s", "sucesso",
              "ollama_total_s", "ollama_carga_s", "ollama_prompt_s", "ollama_geracao_s",
              "tokens_entrada", "tokens_saida", "tokens_saida_por_segundo"]
    with arquivo_csv.open("x", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=campos)
        writer.writeheader()
        for amostra in relatorio["amostras"]:
            base = {campo: amostra[campo] for campo in campos[:7]}
            for etapa in amostra["etapas"]:
                writer.writerow({**base, **etapa})
    return arquivo_json, arquivo_csv


def imprimir_resumo(relatorio):
    print(f"Modo: {relatorio['modo']} | Tempos em milissegundos")
    if relatorio["modo"] == "simulado":
        print("SIMULAÇÃO: mede o fluxo Python, não o desempenho de modelos.")
    for resumo in relatorio["resumos"]:
        total = resumo["total"]
        print(f"\n{resumo['modelo_configurado']} | {resumo['cenario']} | "
              f"sucessos {resumo['sucessos']}/{total['n']} | "
              f"média {total['media_s'] * 1000:.3f} | p95 {total['p95_s'] * 1000:.3f}")
        print(f"  {'Etapa':64} {'Total médio':>12} {'Próprio médio':>14} {'n':>4}")
        for etapa in resumo["etapas"]:
            print(f"  {etapa['etapa']:64} {etapa['inclusivo']['media_s'] * 1000:12.3f} "
                  f"{etapa['exclusivo']['media_s'] * 1000:14.3f} {etapa['inclusivo']['n']:4}")
    falhas_aquecimento = sum(a["estado"] != "concluido" for a in relatorio["aquecimentos"])
    if falhas_aquecimento:
        print(f"Atenção: {falhas_aquecimento} aquecimento(s) falharam; veja o JSON.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelos", nargs="+", help="Modelos econômicos a comparar, sequencialmente.")
    parser.add_argument("--modelo-complexo", help="Candidato complexo opcional para testar o roteamento.")
    parser.add_argument("--cenarios", nargs="+", choices=list(CENARIOS), default=list(CENARIOS))
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--aquecimentos", type=int, default=1)
    parser.add_argument("--contexto", type=int, default=4096)
    parser.add_argument("--limite-resposta", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--simulado", action="store_true")
    parser.add_argument("--saida", type=Path, default=Path(__file__).resolve().parent / "benchmark_results")
    args = parser.parse_args(argv)
    try:
        if args.repeticoes <= 0 or args.aquecimentos < 0:
            raise ValueError("Use repetições positivas e aquecimentos não negativos.")
        base = Configuracao.do_ambiente()
        configuracoes = [replace(
            base, modelo_economico=modelo,
            modelo_complexo=args.modelo_complexo or base.modelo_complexo,
            contexto=args.contexto, limite_resposta=args.limite_resposta, timeout=args.timeout,
        ) for modelo in (args.modelos or [base.modelo_economico])]
    except ValueError as erro:
        parser.error(str(erro))
    try:
        print("Iniciando benchmark simulado." if args.simulado else "Iniciando benchmark com Ollama real.", flush=True)
        relatorio = executar_benchmark(configuracoes, args.cenarios, args.repeticoes,
                                       args.aquecimentos, args.simulado,
                                       progresso=lambda modelo, cenario, fase, numero:
                                       print(f"  {modelo} | {cenario} | {fase} {numero}", flush=True))
        arquivos = salvar_relatorios(relatorio, args.saida)
    except KeyboardInterrupt:
        print("Benchmark interrompido. Nenhum relatório completo foi gerado.")
        return 130
    imprimir_resumo(relatorio)
    for arquivo in arquivos:
        print(f"Relatório: {arquivo}")
    return int(any(a["estado"] != "concluido" for a in relatorio["amostras"] + relatorio["aquecimentos"]))


if __name__ == "__main__":
    raise SystemExit(main())
