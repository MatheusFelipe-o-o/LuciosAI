"""Índice técnico Lucios v1; não mede qualidade de respostas ou competência da GPU."""

from collections import defaultdict
import hashlib
import json
import statistics

from benchmark import CENARIOS


REFERENCIAS = {"limpeza": 0.001, "conversa": 2, "memoria_busca": 2.5,
               "memoria_ambigua": 5, "complexa": 5, "encerramento": 8}


def pontuar(relatorio):
    resultado = {"versao": "Lucios v1", "nota": None, "maximo": 1000,
                 "referencias_s": REFERENCIAS, "provisorio": False}
    if relatorio["modo"] != "ollama_real" or relatorio.get("interrompido"):
        resultado["motivo"] = "Simulação ou rodada interrompida não recebe pontuação."
        return resultado
    amostras = relatorio["amostras"]
    if not amostras:
        resultado["motivo"] = "Nenhuma amostra medida."
        return resultado
    grupos = defaultdict(list)
    for amostra in amostras:
        grupos[(amostra["modelo_configurado"], amostra["cenario"])].append(amostra)
    partes = []
    for (modelo, cenario), grupo in grupos.items():
        tempos = [a["total_s"] for a in grupo if a["estado"] == "concluido"]
        mediana = statistics.median(tempos) if tempos else None
        velocidade = min(1, REFERENCIAS[cenario] / max(mediana, 1e-9)) if tempos else 0
        cv = statistics.pstdev(tempos) / max(statistics.mean(tempos), 1e-9) if len(tempos) > 1 else None
        estabilidade = 1 / (1 + cv) if cv is not None else (0.5 if tempos else 0)
        partes.append({"modelo": modelo, "cenario": cenario, "n": len(grupo),
                       "sucessos": len(tempos), "mediana_s": mediana,
                       "velocidade": velocidade, "estabilidade": estabilidade})
    confiabilidade = sum(a["estado"] == "concluido" for a in amostras) / len(amostras)
    velocidade = statistics.mean(p["velocidade"] for p in partes)
    estabilidade = statistics.mean(p["estabilidade"] for p in partes)
    perfil = {"cenarios": sorted({a["cenario"] for a in amostras}),
              "repeticoes": relatorio["repeticoes"],
              "aquecimentos": relatorio["aquecimentos_por_cenario"],
              "carga": hashlib.sha256(json.dumps(CENARIOS, sort_keys=True).encode()).hexdigest()[:10],
              "configuracoes": [{k: c[k] for k in ("contexto", "limite_resposta", "timeout", "limite_chamadas", "limite_entrada")}
                                | {"roteamento_complexo": bool(c["modelo_complexo"])}
                                for c in relatorio["configuracoes"]]}
    resultado.update(
        nota=round(1000 * confiabilidade * (0.7 * velocidade + 0.3 * estabilidade)),
        confiabilidade=confiabilidade, velocidade=velocidade, estabilidade=estabilidade,
        provisorio=any(p["sucessos"] < 3 for p in partes), por_cenario=partes,
        perfil=hashlib.sha256(json.dumps(perfil, sort_keys=True).encode()).hexdigest()[:10],
        motivo="Índice técnico de latência, confiabilidade e estabilidade. Não avalia qualidade.",
    )
    return resultado
