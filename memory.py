import json
import os
import re
import unicodedata
from datetime import datetime

import ollama


ARQUIVO_MEMORIA_PADRAO = "memoria_lucios.txt"
SEPARADOR_MEMORIA = "=== MEMORIA ==="
FIM_MEMORIA = "=== FIM MEMORIA ==="

_PALAVRAS_VAZIAS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos",
    "e", "em", "essa", "esse", "esta", "este", "eu", "foi", "me",
    "minha", "meu", "na", "nas", "no", "nos", "o", "os", "para",
    "por", "sobre", "um", "uma", "voce",
}
def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", texto)).strip()


def _compactar(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto)).strip()


def _lista_pontos(valor) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    return [_compactar(ponto) for ponto in valor if _compactar(ponto)]


class Memory:
    """Cria, persiste e recupera memórias legíveis, somente quando solicitado."""

    def __init__(
        self,
        model_name: str = "qwen3:8b",
        memory_file: str = ARQUIVO_MEMORIA_PADRAO,
    ):
        self.model_name = model_name
        self.memory_file = memory_file
        self.legacy_file = os.path.join(
            os.path.dirname(memory_file),
            "memoria_lucios.json",
        )

    def criar_memoria(self, conversa: list[dict]) -> dict:
        texto_conversa = "\n".join(
            f"{mensagem['role']}: {mensagem['content']}"
            for mensagem in conversa
            if mensagem.get("role") in {"user", "assistant"}
        )
        prompt = f"""
Analise a conversa e gere uma memória curta, clara e útil para recuperação futura.
O campo "contexto" deve incluir palavras-chave específicas que facilitem encontrar
esta memória por assunto ou título. Não invente fatos. Pontos aprendidos e
desenvolvidos devem ser listas curtas.

CONVERSA:
{texto_conversa}

Responda somente com JSON válido neste formato:
{{
  "titulo": "título curto e específico",
  "contexto": "termos e contexto principal para busca",
  "resumo": "resumo breve do que foi conversado",
  "pontos_aprendidos": ["ponto aprendido"],
  "pontos_desenvolvidos": ["solução, decisão ou trabalho realizado"]
}}
"""
        resposta = ollama.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        conteudo = resposta["message"]["content"].strip()
        conteudo = re.sub(r"^```(?:json)?\s*|\s*```$", "", conteudo, flags=re.IGNORECASE)

        try:
            memoria = json.loads(conteudo)
        except json.JSONDecodeError as erro:
            raise ValueError("O modelo não retornou uma memória em JSON válido.") from erro

        campos_texto = ("titulo", "contexto", "resumo")
        if not isinstance(memoria, dict) or any(
            not isinstance(memoria.get(campo), str) or not memoria[campo].strip()
            for campo in campos_texto
        ):
            raise ValueError("A memória gerada não contém título, contexto e resumo válidos.")

        memoria["titulo"] = _compactar(memoria["titulo"])
        memoria["contexto"] = _compactar(memoria["contexto"])
        memoria["resumo"] = _compactar(memoria["resumo"])
        memoria["pontos_aprendidos"] = _lista_pontos(memoria.get("pontos_aprendidos"))
        memoria["pontos_desenvolvidos"] = _lista_pontos(memoria.get("pontos_desenvolvidos"))
        memoria["data"] = datetime.now().strftime("%d/%m/%Y")
        memoria["hora"] = datetime.now().strftime("%H:%M:%S")
        return memoria

    def _formatar_memoria(self, memoria: dict) -> str:
        aprendidos = _lista_pontos(memoria.get("pontos_aprendidos"))
        desenvolvidos = _lista_pontos(memoria.get("pontos_desenvolvidos"))
        linhas = [
            SEPARADOR_MEMORIA,
            f"Data: {_compactar(memoria.get('data', ''))}",
            f"Hora: {_compactar(memoria.get('hora', ''))}",
            f"Título: {_compactar(memoria.get('titulo', ''))}",
            f"Contexto: {_compactar(memoria.get('contexto', ''))}",
            f"Resumo: {_compactar(memoria.get('resumo', ''))}",
            "Pontos aprendidos:",
            *(f"- {ponto}" for ponto in aprendidos),
            "Pontos desenvolvidos:",
            *(f"- {ponto}" for ponto in desenvolvidos),
            FIM_MEMORIA,
            "",
        ]
        return "\n".join(linhas)

    def _ler_memorias_txt(self) -> list[dict]:
        if not os.path.exists(self.memory_file):
            return []
        with open(self.memory_file, "r", encoding="utf-8") as arquivo:
            conteudo = arquivo.read()

        memorias = []
        for bloco in conteudo.split(SEPARADOR_MEMORIA)[1:]:
            bloco = bloco.split(FIM_MEMORIA, 1)[0]
            memoria = {
                "data": "",
                "hora": "",
                "titulo": "",
                "contexto": "",
                "resumo": "",
                "pontos_aprendidos": [],
                "pontos_desenvolvidos": [],
            }
            secao = None
            for linha in bloco.splitlines():
                linha = linha.strip()
                if linha.startswith("Data:"):
                    memoria["data"] = linha.partition(":")[2].strip()
                    secao = None
                elif linha.startswith("Hora:"):
                    memoria["hora"] = linha.partition(":")[2].strip()
                    secao = None
                elif linha.startswith("Título:"):
                    memoria["titulo"] = linha.partition(":")[2].strip()
                    secao = None
                elif linha.startswith("Contexto:"):
                    memoria["contexto"] = linha.partition(":")[2].strip()
                    secao = None
                elif linha.startswith("Resumo:"):
                    memoria["resumo"] = linha.partition(":")[2].strip()
                    secao = None
                elif linha == "Pontos aprendidos:":
                    secao = "pontos_aprendidos"
                elif linha == "Pontos desenvolvidos:":
                    secao = "pontos_desenvolvidos"
                elif linha.startswith("- ") and secao:
                    memoria[secao].append(linha[2:].strip())
            if memoria["titulo"] and memoria["contexto"]:
                memorias.append(memoria)
        return memorias

    def _ler_memorias_legadas(self) -> list[dict]:
        if not os.path.exists(self.legacy_file):
            return []
        try:
            with open(self.legacy_file, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except (OSError, json.JSONDecodeError) as erro:
            raise ValueError(f"Não foi possível ler a memória JSON antiga: {erro}") from erro

        if not isinstance(dados, list):
            return []

        memorias = []
        for item in dados:
            if not isinstance(item, dict) or not item.get("titulo"):
                continue
            assuntos = _lista_pontos(item.get("assuntos"))
            resolvido = _compactar(item.get("resolvido", ""))
            contexto = _compactar(item.get("contexto") or ", ".join(assuntos) or resolvido)
            if not contexto:
                contexto = _compactar(item.get("resumo", ""))
            memoria = {
                "data": _compactar(item.get("data", "")),
                "hora": _compactar(item.get("hora", "")),
                "titulo": _compactar(item["titulo"]),
                "contexto": contexto,
                "resumo": _compactar(item.get("resumo", "")),
                "pontos_aprendidos": _lista_pontos(
                    item.get("pontos_aprendidos") or assuntos
                ),
                "pontos_desenvolvidos": _lista_pontos(
                    item.get("pontos_desenvolvidos") or resolvido
                ),
            }
            if memoria["titulo"] and memoria["contexto"]:
                memorias.append(memoria)
        return memorias

    def _sincronizar_memorias_legadas(self) -> list[dict]:
        memorias_txt = self._ler_memorias_txt()
        chaves_txt = {
            (_normalizar(item["titulo"]), item.get("data", ""), item.get("hora", ""))
            for item in memorias_txt
        }
        memorias_novas = [
            item for item in self._ler_memorias_legadas()
            if (_normalizar(item["titulo"]), item.get("data", ""), item.get("hora", ""))
            not in chaves_txt
        ]
        if memorias_novas:
            os.makedirs(os.path.dirname(os.path.abspath(self.memory_file)), exist_ok=True)
            with open(self.memory_file, "a", encoding="utf-8") as arquivo:
                for item in memorias_novas:
                    arquivo.write(self._formatar_memoria(item))
            memorias_txt.extend(memorias_novas)
        return memorias_txt

    def salvar_memoria(self, memoria: dict) -> None:
        """Acrescenta uma memória ao TXT legível, migrando o JSON antigo se houver."""
        self._sincronizar_memorias_legadas()
        os.makedirs(os.path.dirname(os.path.abspath(self.memory_file)), exist_ok=True)
        with open(self.memory_file, "a", encoding="utf-8") as arquivo:
            arquivo.write(self._formatar_memoria(memoria))

    def buscar_memorias(self, consulta: str, limite: int = 3) -> list[dict]:
        """Busca sob demanda somente nos campos título e contexto."""
        memorias = self._sincronizar_memorias_legadas()

        consulta_normalizada = _normalizar(consulta)
        termos = {
            termo for termo in consulta_normalizada.split()
            if len(termo) > 2 and termo not in _PALAVRAS_VAZIAS
        }
        if not termos:
            return []

        resultados = []
        for memoria in memorias:
            titulo = _normalizar(memoria.get("titulo", ""))
            contexto = _normalizar(memoria.get("contexto", ""))
            titulo_termos = set(titulo.split())
            contexto_termos = set(contexto.split())
            pontuacao = 3 * len(termos & titulo_termos) + len(termos & contexto_termos)

            if consulta_normalizada and consulta_normalizada in titulo:
                pontuacao += 8
            elif consulta_normalizada and consulta_normalizada in contexto:
                pontuacao += 4

            if pontuacao:
                resultados.append((pontuacao, memoria))

        resultados.sort(key=lambda item: item[0], reverse=True)
        return [memoria for _, memoria in resultados[:limite]]

    def listar_memorias_recentes(self, limite: int = 5) -> list[dict]:
        """Lista as memórias mais recentes pela ordem em que foram salvas."""
        if limite <= 0:
            return []
        memorias = self._sincronizar_memorias_legadas()
        return list(reversed(memorias[-limite:]))
