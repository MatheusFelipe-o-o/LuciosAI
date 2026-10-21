from dataclasses import asdict
import unittest
from unittest.mock import Mock

from Agent import LuciosAgent
from orchestrator import Configuracao, Estado, Orquestrador, medir_etapa


class MedicaoTests(unittest.TestCase):
    def test_tempos_inclusivos_e_exclusivos_com_relogio_controlado(self):
        tempo = [0]
        medicoes = []
        with medir_etapa(medicoes, "pai", lambda: tempo[0]) as pai:
            tempo[0] = 2
            with medir_etapa(pai.subetapas, "filho", lambda: tempo[0]):
                tempo[0] = 5
            tempo[0] = 10
        self.assertEqual(pai.duracao, 10)
        self.assertEqual(pai.subetapas[0].duracao, 3)
        self.assertEqual(pai.exclusiva, 7)
        self.assertTrue(pai.sucesso)

    def test_falha_preserva_tempo_e_nao_altera_excecao(self):
        tempo = [0]
        medicoes = []
        with self.assertRaisesRegex(ValueError, "exemplo"):
            with medir_etapa(medicoes, "falha", lambda: tempo[0]):
                tempo[0] = 4
                raise ValueError("exemplo")
        self.assertEqual(medicoes[0].duracao, 4)
        self.assertFalse(medicoes[0].sucesso)

    def test_inferencia_registra_apenas_metricas_numericas_permitidas(self):
        cliente = Mock()
        cliente.chat.return_value = {
            "message": {"content": "resposta privada"},
            "load_duration": 100, "eval_count": 10, "eval_duration": 1000000000,
            "prompt_eval_count": -1, "total_duration": "invalido",
            "segredo": "nao exportar",
        }
        agent = LuciosAgent(configuracao=Configuracao(), cliente=cliente)
        agent.chat("Olá")
        execucao = next(m for m in agent.ultimo_resultado.medicoes if m.etapa == "execucao")
        inferencia = next(m for m in execucao.subetapas if m.etapa == "inferencia_resposta")
        self.assertNotIn("recuperacao_memoria", [m.etapa for m in execucao.subetapas])
        self.assertEqual(inferencia.metricas, {
            "load_duration": 100, "eval_count": 10, "eval_duration": 1000000000,
        })
        serialized = str([asdict(m) for m in agent.ultimo_resultado.medicoes])
        self.assertNotIn("resposta privada", serialized)
        self.assertNotIn("nao exportar", serialized)
        self.assertGreaterEqual(agent.ultimo_resultado.duracao_chat, agent.ultimo_resultado.duracao)
        self.assertEqual(agent.ultimo_resultado.medicoes[-1].etapa, "finalizacao_chat")

    def test_entrada_invalida_nao_inventa_etapas_posteriores(self):
        o = Orquestrador(Configuracao(), Mock(), Mock())
        resultado = o.executar("", Mock(), Mock())
        self.assertEqual(resultado.estado, Estado.FALHOU)
        self.assertEqual([m.etapa for m in resultado.medicoes], ["validacao"])
        self.assertFalse(resultado.medicoes[0].sucesso)

    def test_falha_de_modelo_marca_inferencia_e_execucao(self):
        cliente = Mock()
        cliente.chat.side_effect = ConnectionError("offline")
        agent = LuciosAgent(configuracao=Configuracao(), cliente=cliente)
        agent.chat("Olá")
        execucao = next(m for m in agent.ultimo_resultado.medicoes if m.etapa == "execucao")
        self.assertFalse(execucao.sucesso)
        self.assertFalse(execucao.subetapas[-1].sucesso)
        self.assertEqual(execucao.subetapas[-1].etapa, "inferencia_resposta")

    def test_encerramento_cronometra_resumo_persistencia_e_limpeza(self):
        agent = LuciosAgent(configuracao=Configuracao(), cliente=Mock())
        agent.memory_manager = Mock()
        agent.memory_manager.criar_memoria.return_value = {"titulo": "Exemplo"}
        agent.conversa = [{"role": "user", "content": "exemplo sintético"}]
        agent.end_conversation()
        self.assertEqual(agent.estado_encerramento, "concluido")
        self.assertEqual([m.etapa for m in agent.medicoes_encerramento], [
            "geracao_resumo", "persistencia_memoria", "limpeza_conversa",
        ])
        self.assertTrue(all(m.sucesso for m in agent.medicoes_encerramento))

    def test_falha_de_resumo_nao_inventa_persistencia_executada(self):
        agent = LuciosAgent(configuracao=Configuracao(), cliente=Mock())
        agent.memory_manager = Mock()
        agent.memory_manager.criar_memoria.side_effect = ValueError("erro")
        agent.conversa = [{"role": "user", "content": "exemplo sintético"}]
        agent.end_conversation()
        self.assertEqual(agent.estado_encerramento, "falhou")
        self.assertEqual(len(agent.medicoes_encerramento), 1)
        self.assertFalse(agent.medicoes_encerramento[0].sucesso)
        self.assertEqual(len(agent.conversa), 1)


if __name__ == "__main__":
    unittest.main()
