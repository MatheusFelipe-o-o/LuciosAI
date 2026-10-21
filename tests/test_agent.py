import unittest
from threading import Event
from unittest.mock import Mock, patch

import ollama

from Agent import LuciosAgent
from main import _formatar_para_terminal
from orchestrator import Configuracao, Estado


class ConciliacaoTests(unittest.TestCase):
    def setUp(self):
        self.cliente = Mock()
        self.cliente.chat.side_effect = lambda **kwargs: ollama.chat(**kwargs)
        self.agent = LuciosAgent(cliente=self.cliente, configuracao=Configuracao())
        self.agent.memory_manager = Mock()

    @patch("Agent.ollama.chat")
    def test_conversa_comum_faz_uma_chamada_sem_ler_memoria(self, chat):
        chat.return_value = {"message": {"content": "**Olá!**"}}
        self.assertEqual(self.agent.chat("Olá, bom dia!"), "**Olá!**")
        chat.assert_called_once()
        args = chat.call_args.kwargs
        self.assertEqual(args["options"]["num_ctx"], 4096)
        self.assertIn("Markdown", args["messages"][0]["content"])
        self.assertEqual(len(self.agent.conversa), 2)
        self.agent.memory_manager.buscar_memorias.assert_not_called()
        self.agent.memory_manager.listar_memorias_recentes.assert_not_called()

    @patch("Agent.ollama.chat")
    def test_listagem_explicita_nao_chama_classificador(self, chat):
        result = self.agent._classificar_pedido_memoria("Liste as últimas conversas")
        self.assertEqual(result, {"acao": "listar_recentes", "consulta": ""})
        chat.assert_not_called()

    @patch("Agent.ollama.chat")
    def test_busca_explicita_extrai_assunto_sem_modelo(self, chat):
        result = self.agent._classificar_pedido_memoria("Lembra sobre orçamento")
        self.assertEqual(result, {"acao": "buscar", "consulta": "orcamento"})
        chat.assert_not_called()

    @patch("Agent.ollama.chat")
    def test_caso_ambiguo_usa_classificador_limitado(self, chat):
        chat.return_value = {"message": {"content": '{"acao":"nenhuma","consulta":""}'}}
        self.assertEqual(
            self.agent._classificar_pedido_memoria("Como funciona sua memória?"),
            {"acao": "nenhuma", "consulta": ""},
        )
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs["options"], {
            "temperature": 0, "num_ctx": 512, "num_predict": 80,
        })

    @patch("Agent.ollama.chat")
    def test_classificador_rejeita_respostas_invalidas(self, chat):
        for content in ('[]', 'null', 'invalido', '{"acao":[],"consulta":""}',
                        '{"acao":"buscar","consulta":123}'):
            with self.subTest(content=content):
                chat.return_value = {"message": {"content": content}}
                self.assertEqual(
                    self.agent._classificar_pedido_memoria_com_modelo("memória"),
                    {"acao": "nenhuma", "consulta": ""},
                )

    @patch("Agent.ollama.chat")
    def test_busca_injeta_somente_memorias_retornadas(self, chat):
        self.agent.memory_manager.buscar_memorias.return_value = [{
            "titulo": "Orçamento", "contexto": "Projeto de exemplo", "resumo": "Definir custo",
        }]
        chat.return_value = {"message": {"content": "Vamos continuar."}}
        self.agent.chat("Lembra sobre orçamento")
        self.agent.memory_manager.buscar_memorias.assert_called_once_with("orcamento")
        chat.assert_called_once()
        self.assertIn("Definir custo", chat.call_args.kwargs["messages"][0]["content"])

    def test_limpar_preserva_memoria_persistida(self):
        self.agent.conversa = [{"role": "user", "content": "exemplo"}]
        self.agent.clear_memory()
        self.assertEqual(self.agent.conversa, [])
        self.agent.memory_manager.salvar_memoria.assert_not_called()

    def test_encerrar_salva_antes_de_limpar(self):
        self.agent.conversa = [{"role": "user", "content": "exemplo"}]
        registro = {"titulo": "Exemplo"}
        self.agent.memory_manager.criar_memoria.return_value = registro
        reply = self.agent.end_conversation()
        self.agent.memory_manager.criar_memoria.assert_called_once_with(
            [{"role": "user", "content": "exemplo"}]
        )
        self.agent.memory_manager.salvar_memoria.assert_called_once_with(registro)
        self.assertEqual(self.agent.conversa, [])
        self.assertIn("Exemplo", reply)

    def test_falha_ao_salvar_preserva_conversa(self):
        self.agent.conversa = [{"role": "user", "content": "exemplo"}]
        self.agent.memory_manager.criar_memoria.side_effect = ValueError("JSON inválido")
        self.assertIn("Erro", self.agent.end_conversation())
        self.assertEqual(len(self.agent.conversa), 1)
        self.agent.memory_manager.salvar_memoria.assert_not_called()

    @patch("Agent.ollama.chat", side_effect=RuntimeError("indisponível"))
    def test_falha_de_inferencia_nao_adiciona_turno_incompleto(self, chat):
        self.assertIn("erro", self.agent.chat("Olá"))
        self.assertEqual(self.agent.conversa, [])

    def test_markdown_do_terminal_preservado(self):
        with patch("main.sys.stdout.isatty", return_value=False):
            self.assertEqual(_formatar_para_terminal("**Olá**"), "**Olá**")
        with patch("main.sys.stdout.isatty", return_value=True):
            self.assertEqual(_formatar_para_terminal("**Olá**"), "\033[1mOlá\033[0m")

    def test_modelo_complexo_selecionado_sem_mudar_modelo_da_memoria(self):
        cliente = Mock()
        cliente.list.return_value = {"models": [{"model": "grande:8b"}]}
        cliente.chat.return_value = {"message": {"content": "Plano de exemplo"}}
        agent = LuciosAgent(configuracao=Configuracao(modelo_complexo="grande:8b"), cliente=cliente)
        self.assertEqual(agent.chat("Planeje uma arquitetura"), "Plano de exemplo")
        self.assertEqual(cliente.chat.call_args.kwargs["model"], "grande:8b")
        self.assertEqual(agent.model_name, "llama3.2")
        self.assertEqual(agent.memory_manager.model_name, "llama3.2")

    @patch("Agent.ollama.chat")
    def test_fallback_memoria_e_resposta_compartilham_orcamento(self, chat):
        chat.side_effect = [
            {"message": {"content": '{"acao":"nenhuma","consulta":""}'}},
            {"message": {"content": "Explicação"}},
        ]
        self.assertEqual(self.agent.chat("Como funciona sua memória?"), "Explicação")
        self.assertEqual(self.agent.ultimo_resultado.chamadas_modelo, 2)
        self.assertEqual(self.agent.ultimo_resultado.estado, Estado.CONCLUIDO)

    @patch("Agent.ollama.chat")
    def test_resposta_vazia_nao_entra_na_conversa(self, chat):
        chat.return_value = {"message": {"content": ""}}
        self.assertIn("erro", self.agent.chat("Olá"))
        self.assertEqual(self.agent.conversa, [])
        self.assertEqual(self.agent.ultimo_resultado.estado, Estado.FALHOU)

    @patch("Agent.ollama.chat")
    def test_comando_limpar_passa_pelo_nucleo_sem_inferencia(self, chat):
        self.agent.conversa = [{"role": "user", "content": "exemplo"}]
        self.agent.chat("limpar")
        self.assertEqual(self.agent.ultimo_resultado.estado, Estado.CONCLUIDO)
        self.assertEqual(self.agent.conversa, [])
        chat.assert_not_called()

    def test_cliente_local_recebe_timeout_configurado(self):
        with patch("Agent.ollama.Client") as client:
            LuciosAgent(configuracao=Configuracao(timeout=20))
            client.assert_called_once_with(host="http://127.0.0.1:11434", timeout=20)

    def test_cancelamento_descarta_resposta_sem_alterar_conversa(self):
        cancelar = Event()
        def responder(**kwargs):
            cancelar.set()
            return {"message": {"content": "resposta tardia"}}
        self.cliente.chat.side_effect = responder
        self.assertIn("cancelada", self.agent.chat("Olá", cancelar))
        self.assertEqual(self.agent.conversa, [])
        self.assertEqual(self.agent.ultimo_resultado.estado, Estado.CANCELADO)


if __name__ == "__main__":
    unittest.main()
