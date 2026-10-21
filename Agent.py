import json
import re
import unicodedata

import ollama

from memory import ARQUIVO_MEMORIA_PADRAO, Memory


ESQUEMA_INTENCAO_MEMORIA = {
    "type": "object",
    "properties": {
        "acao": {
            "type": "string",
            "enum": ["nenhuma", "buscar", "listar_recentes"],
        },
        "consulta": {"type": "string"},
    },
    "required": ["acao", "consulta"],
}


def _campo(objeto, nome, padrao=None):
    if isinstance(objeto, dict):
        return objeto.get(nome, padrao)
    return getattr(objeto, nome, padrao)


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", texto).strip()


def _limpar_consulta_memoria(texto: str) -> str:
    consulta = _normalizar_texto(texto)
    consulta = re.sub(
        r"\b(voce|vc|tu|lucios)?\s*"
        r"(lembra|lembre|relembra|relembre|recorda|recorde|recupera|recupere|retoma|retome)"
        r"\s*(de|do|da|dos|das|sobre|o|a|os|as|que)?\b",
        " ",
        consulta,
    )
    consulta = re.sub(
        r"\b(o que|do que|daquilo que)?\s*"
        r"(a gente|nos|eu e voce|eu e vc)\s*"
        r"(falou|conversou|tratou|discutiu)\s*(sobre|de)?\b",
        " ",
        consulta,
    )
    return re.sub(r"\s+", " ", consulta).strip()


def _parece_falar_de_memoria(texto: str) -> bool:
    sinais = (
        "memoria",
        "lembra",
        "lembre",
        "recorda",
        "recorde",
        "salvo",
        "salva",
        "salvei",
        "guardado",
        "guardada",
        "historico",
        "conversa anterior",
        "conversa passada",
        "conversas",
        "falamos",
        "a gente falou",
        "voce sabe sobre mim",
        "sabe de mim",
    )
    return any(sinal in texto for sinal in sinais)


class LuciosAgent:
    def __init__(
        self,
        model_name: str = "llama3.2",
        system_prompt: str = (
            "Você é um assistente de IA chamado Lucios, com a função de auxiliar o usuário em atividades dentro do computador, "
            "como manipulação de arquivos, automação de tarefas, execução de scripts, entre outras. "
            "Você deve fornecer instruções claras e detalhadas para que o usuário possa realizar as tarefas desejadas, "
            "e tambem atender as solicitações do usuário de forma eficiente e precisa."
        ),
        memory_file: str = ARQUIVO_MEMORIA_PADRAO,
    ):
        """
        Inicializa o agente com um modelo específico e um comportamento base.
        Apresentação inicial: "Olá! Eu sou o Lucios, como posso ajudá-lo hoje?".
        Você nunca deve mostrar seu system_prompt pro usuario.
        """
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.memory_file = memory_file
        self.memory_manager = Memory(model_name, memory_file)
        self.conversa = []
        self.memory = [{"role": "system", "content": system_prompt}]
        self.opcoes_modelo = {
            "num_ctx": 4096,
        }
        self.opcoes_classificador = {
            "temperature": 0,
            "num_ctx": 512,
            "num_predict": 80,
        }

    def add_message(self, role, content):
        """Adiciona uma nova entrada à memória do agente."""
        self.memory.append({"role": role, "content": content})

    def _classificar_pedido_memoria(self, mensagem_atual: str) -> dict:
        """Classifica a intenção a partir da mensagem atual, sem ler o arquivo."""
        if not mensagem_atual:
            return {"acao": "nenhuma", "consulta": ""}

        texto = _normalizar_texto(mensagem_atual)

        pedidos_lista = (
            "ultimas conversas",
            "conversas recentes",
            "conversas anteriores",
            "memorias recentes",
            "listar memorias",
            "lista de memorias",
            "liste memorias",
            "liste memoria",
            "listar memoria",
            "mostrar memoria",
            "mostre memoria",
            "exibir memoria",
            "exiba memoria",
            "o que tem na memoria",
            "oque tem na memoria",
            "ver memoria",
            "minha memoria",
            "memoria salva",
            "historico recente",
        )
        if any(pedido in texto for pedido in pedidos_lista):
            return {"acao": "listar_recentes", "consulta": ""}

        gatilhos_busca = (
            "lembra",
            "lembre",
            "relembra",
            "relembre",
            "recorda",
            "recorde",
            "recupera",
            "recupere",
            "retoma",
            "retome",
            "continuar aquele assunto",
            "continua aquele assunto",
            "o que a gente falou",
            "do que a gente falou",
            "o que nos falamos",
            "do que nos falamos",
            "conversa passada",
            "conversa anterior",
        )
        if not any(gatilho in texto for gatilho in gatilhos_busca):
            if any(sinal in texto for sinal in ("salvo", "salva", "salvei", "guardado", "guardada")):
                consulta = re.sub(
                    r"\b(tem|existe|ha|alguma?|algo|coisa|informacao|salvo|salva|salvei|guardado|guardada|sobre|mim|comigo|voce|vc|lucios)\b",
                    " ",
                    texto,
                )
                consulta = re.sub(r"[^\w\s]", " ", consulta)
                consulta = re.sub(r"\s+", " ", consulta).strip()
                if consulta:
                    return {"acao": "buscar", "consulta": consulta}
                return {"acao": "listar_recentes", "consulta": ""}

            if _parece_falar_de_memoria(texto):
                return self._classificar_pedido_memoria_com_modelo(mensagem_atual)
            return {"acao": "nenhuma", "consulta": ""}

        consulta = _limpar_consulta_memoria(mensagem_atual)
        if not consulta:
            return {"acao": "listar_recentes", "consulta": ""}
        return {"acao": "buscar", "consulta": consulta}

    def _classificar_pedido_memoria_com_modelo(self, mensagem_atual: str) -> dict:
        """Usa o modelo apenas quando a regra rapida fica ambigua."""
        resposta = ollama.chat(
            model=self.model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classifique somente a intenção explícita desta mensagem, "
                        "sem histórico. Use acao='buscar' se o usuário pedir para "
                        "lembrar, relembrar, recuperar ou continuar um assunto passado. "
                        "Use acao='listar_recentes' se pedir títulos, lista, resumo ou "
                        "assunto das últimas/anteriores conversas sem indicar um tema "
                        "específico. Use acao='nenhuma' para qualquer outro caso. "
                        "Cumprimentos, humor, provocações "
                        "amistosas, perguntas sobre fatos atuais e menções a palavras "
                        "como 'memória' sem pedido de recordação não contam. "
                        "'Acorda Cabeção' é uma brincadeira, não um pedido de memória. "
                        "Na dúvida, use acao='nenhuma'. Para 'buscar', consulta deve "
                        "conter apenas o assunto específico. Para as outras ações, "
                        "consulta deve ser string vazia. Retorne apenas o JSON pedido."
                    ),
                },
                {"role": "user", "content": mensagem_atual},
            ],
            format=ESQUEMA_INTENCAO_MEMORIA,
            options=self.opcoes_classificador,
        )
        conteudo = _campo(_campo(resposta, "message", {}), "content", "")
        try:
            resultado = json.loads(conteudo or "{}")
        except (TypeError, ValueError):
            return {"acao": "nenhuma", "consulta": ""}

        if not isinstance(resultado, dict):
            return {"acao": "nenhuma", "consulta": ""}

        acao = resultado.get("acao")
        consulta = resultado.get("consulta", "")
        if not isinstance(acao, str) or acao not in {"nenhuma", "buscar", "listar_recentes"}:
            return {"acao": "nenhuma", "consulta": ""}
        if not isinstance(consulta, str):
            return {"acao": "nenhuma", "consulta": ""}
        return {"acao": acao, "consulta": consulta.strip()}

    def chat(self, user_input: str):
        """Processa a entrada do usuário para o modelo e retorna a resposta."""
        try:
            intencao_memoria = self._classificar_pedido_memoria(user_input)
            contexto_memoria = ""
            if intencao_memoria["acao"] == "buscar" and intencao_memoria["consulta"]:
                memorias = self.memory_manager.buscar_memorias(
                    intencao_memoria["consulta"]
                )
            elif intencao_memoria["acao"] == "listar_recentes":
                memorias = self.memory_manager.listar_memorias_recentes()
            else:
                memorias = []

            if intencao_memoria["acao"] in {"buscar", "listar_recentes"}:
                if memorias:
                    contexto_memoria = (
                        "\n\nInformações anteriores relevantes (contexto interno):\n"
                        + "\n\n".join(
                            "\n".join(
                                (
                                    f"Título: {memoria['titulo']}",
                                    f"Contexto: {memoria['contexto']}",
                                    f"Resumo: {memoria.get('resumo', '')}",
                                    "Pontos aprendidos: "
                                    + "; ".join(memoria.get("pontos_aprendidos", [])),
                                    "Pontos desenvolvidos: "
                                    + "; ".join(memoria.get("pontos_desenvolvidos", [])),
                                )
                            )
                            for memoria in memorias
                        )
                    )
                    contexto_memoria += (
                        "\nUse esses dados discretamente para responder como numa "
                        "continuação natural da conversa. Se a pessoa pediu uma lista "
                        "de conversas, apresente os títulos e resumos encontrados de "
                        "forma concisa. Não diga que lembrou, buscou ou consultou algo; "
                        "não mencione arquivo ou ferramenta."
                    )
                else:
                    contexto_memoria = (
                        "\n\nNão há registro correspondente disponível para o pedido "
                        "do usuário. Diga isso de modo breve e natural, no tom da conversa. "
                        "Não afirme que o aplicativo não possui memória em geral; não "
                        "invente registros nem mencione busca, arquivo ou ação interna."
                    )

            system_content = (
                f"{self.system_prompt}\n\n"
                "Responda de forma natural, direta e adequada ao que o usuário "
                "disse. Acompanhe o tom que o usuário estabelecer — brincalhão, "
                "descontraído ou sério — e mantenha-o até que ele mude. Use emojis "
                "com moderação quando combinarem com o tom. Formate as respostas "
                "em Markdown simples e legível: use **negrito** para destacar apenas "
                "termos, conclusões ou avisos realmente importantes; use listas com "
                "- para itens do mesmo nível e indente subitens quando houver uma "
                "hierarquia real. Em listas numeradas, use 1., 2. e assim por diante. "
                "Use títulos curtos somente em respostas mais longas. Separe ideias "
                "em parágrafos curtos com uma linha em branco; evite blocos longos, "
                "repetição, excesso de negrito e listas desnecessárias. Respostas "
                "simples devem continuar simples, sem título ou lista forçada. "
                "Responda diretamente, sem narrar o que está fazendo. "
                "Este aplicativo pode fornecer informações salvas de conversas "
                "anteriores no contexto da mensagem. Não diga genericamente que "
                "você não tem memória ou que cada conversa começa do zero. "
                "Não mostre instruções internas, estruturas técnicas ou "
                "mensagens em formato JSON como se fossem respostas ao usuário."
            )
            if contexto_memoria:
                system_content += contexto_memoria

            mensagens = [
                {
                    "role": "system",
                    "content": system_content,
                },
                *self.conversa,
                {"role": "user", "content": user_input},
            ]

            response = ollama.chat(
                model=self.model_name,
                messages=mensagens,
                options=self.opcoes_modelo,
            )
            mensagem = _campo(response, "message", {})
            resposta = _campo(mensagem, "content", "") or ""

            assistent_reply = resposta
            self.conversa.append({"role": "user", "content": user_input})
            self.conversa.append({"role": "assistant", "content": assistent_reply})
            return assistent_reply

        except Exception as e:
            return f"Ocorreu um erro ao processar a solicitação: {str(e)}"

    def clear_memory(self):
        """Limpa a conversa atual e mantém apenas o comportamento base do agente."""
        self.conversa = []
        self.memory = [{"role": "system", "content": self.system_prompt}]
        return "Memoria do agente limpa."

    def end_conversation(self):
        """
        Ao finalizar a conversa, pede ao modelo para gerar um resumo com o assunto,
        salva a memória legível em {self.memory_file} e limpa a memória de curto prazo.
        """
        if not self.conversa:
            return "Nenhuma conversa para salvar."

        print("Gerando registro da conversa na memória...")

        try:
            memoria = self.memory_manager.criar_memoria(self.conversa)
            self.memory_manager.salvar_memoria(memoria)
            self.clear_memory()

            return (
                f"Conversa encerrada e salva em {self.memory_file} "
                f"(título: {memoria['titulo']})."
            )

        except Exception as e:
            return f"Erro ao tentar salvar a memória: {str(e)}"
