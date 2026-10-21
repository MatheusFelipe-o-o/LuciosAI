from threading import Event
import unittest
from unittest.mock import Mock, patch

from orchestrator import Configuracao, Estado, Orquestrador, Resultado


class OrquestradorTests(unittest.TestCase):
    def criar(self, **opcoes):
        self.chat = Mock(return_value={"message": {"content": "Resposta"}})
        self.catalogo = Mock(return_value=["pequeno:latest", "grande:8b"])
        self.limpar = Mock(return_value="Memória limpa.")
        self.tempo = 0
        config = Configuracao(modelo_economico="pequeno", **opcoes)
        self.orquestrador = Orquestrador(config, self.chat, self.catalogo, lambda: self.tempo)
        self.responder = Mock(side_effect=lambda texto, modelo, contexto:
                              contexto.chamar_modelo(model=modelo)["message"]["content"])

    def executar(self, texto="Olá", **kwargs):
        return self.orquestrador.executar(texto, self.responder, self.limpar, **kwargs)

    def test_fluxo_completo_e_modelo_economico(self):
        self.criar()
        resultado = self.executar()
        self.assertEqual(resultado.estados, [Estado.RECEBIDO, Estado.VALIDANDO,
                         Estado.EXECUTANDO, Estado.VERIFICANDO, Estado.CONCLUIDO])
        self.assertEqual(resultado.decisao.modelo, "pequeno")
        self.assertEqual(resultado.chamadas_modelo, 1)
        self.catalogo.assert_not_called()

    def test_limpar_nao_usa_modelo_ou_catalogo(self):
        self.criar()
        resultado = self.executar(" LIMPAR ")
        self.assertEqual(resultado.estado, Estado.CONCLUIDO)
        self.assertEqual(resultado.decisao.complexidade, "simples")
        self.assertEqual(resultado.chamadas_modelo, 0)
        self.limpar.assert_called_once()
        self.chat.assert_not_called()
        self.responder.assert_not_called()
        self.catalogo.assert_not_called()

    def test_pedido_complexo_usa_modelo_instalado(self):
        self.criar(modelo_complexo="grande:8b")
        resultado = self.executar("Planeje a arquitetura do projeto")
        self.assertEqual(resultado.decisao.modelo, "grande:8b")
        self.chat.assert_called_once_with(model="grande:8b")

    def test_alias_latest_do_catalogo(self):
        self.criar(modelo_complexo="grande")
        self.catalogo.return_value = ["grande:latest"]
        self.assertEqual(self.executar("Planeje as etapas").decisao.modelo, "grande")

    def test_complexo_nao_instalado_faz_fallback_sem_download(self):
        self.criar(modelo_complexo="ausente")
        resultado = self.executar("Faça uma análise detalhada")
        self.assertEqual(resultado.decisao.modelo, "pequeno")
        self.assertIn("não instalado", resultado.decisao.motivo)
        self.chat.assert_called_once_with(model="pequeno")

    def test_complexo_nao_configurado_nao_consulta_catalogo(self):
        self.criar()
        resultado = self.executar("Explique passo a passo")
        self.assertIn("não configurado", resultado.decisao.motivo)
        self.catalogo.assert_not_called()

    def test_falha_do_catalogo_faz_fallback(self):
        self.criar(modelo_complexo="grande:8b")
        self.catalogo.side_effect = ConnectionError("offline")
        resultado = self.executar("Investigue a falha")
        self.assertEqual(resultado.estado, Estado.CONCLUIDO)
        self.assertIn("catálogo", resultado.decisao.motivo)

    def test_entrada_invalida_nao_chama_modelo(self):
        self.criar()
        for texto in (None, [], {}, 2, "", "  ", "a" * 16001):
            with self.subTest(tipo=type(texto).__name__):
                self.assertEqual(self.executar(texto).estado, Estado.FALHOU)
        self.chat.assert_not_called()
        self.limpar.assert_not_called()

    def test_resultado_vazio_ou_tipo_invalido_falha(self):
        self.criar()
        for valor in ("", "  ", None, [], 12):
            with self.subTest(valor=valor):
                self.responder.side_effect = None
                self.responder.return_value = valor
                resultado = self.executar()
                self.assertEqual(resultado.estado, Estado.FALHOU)
                self.assertEqual(resultado.resposta, "")

    def test_excecao_nao_e_sucesso_e_nao_ha_retry(self):
        self.criar()
        self.chat.side_effect = RuntimeError("falhou")
        resultado = self.executar()
        self.assertEqual(resultado.estado, Estado.FALHOU)
        self.assertEqual(resultado.erro, "falhou")
        self.chat.assert_called_once()

    def test_terceira_chamada_e_impedida(self):
        self.criar()
        def tres_chamadas(texto, modelo, contexto):
            for _ in range(3):
                contexto.chamar_modelo(model=modelo)
            return "não deve chegar aqui"
        self.responder.side_effect = tres_chamadas
        resultado = self.executar()
        self.assertEqual(resultado.estado, Estado.FALHOU)
        self.assertEqual(resultado.chamadas_modelo, 2)
        self.assertEqual(self.chat.call_count, 2)

    def test_cancelamento_antes_da_execucao(self):
        self.criar()
        cancelar = Event()
        cancelar.set()
        self.assertEqual(self.executar(cancelar=cancelar).estado, Estado.CANCELADO)
        self.chat.assert_not_called()
        self.limpar.assert_not_called()

    def test_cancelamento_apos_inferencia_descarta_resposta(self):
        self.criar()
        cancelar = Event()
        def chamar(**kwargs):
            cancelar.set()
            return {"message": {"content": "resposta tardia"}}
        self.chat.side_effect = chamar
        resultado = self.executar(cancelar=cancelar)
        self.assertEqual(resultado.estado, Estado.CANCELADO)
        self.assertEqual(resultado.resposta, "")

    def test_timeout_apos_inferencia_descarta_resposta(self):
        self.criar(timeout=5)
        def chamar(**kwargs):
            self.tempo = 6
            return {"message": {"content": "resposta tardia"}}
        self.chat.side_effect = chamar
        resultado = self.executar()
        self.assertEqual(resultado.estado, Estado.FALHOU)
        self.assertIn("tempo", resultado.erro)
        self.assertEqual(resultado.duracao, 6)
        self.assertEqual(resultado.resposta, "")

    def test_nao_se_reabre_estado_terminal(self):
        resultado = Resultado(estados=[Estado.CONCLUIDO])
        with self.assertRaises(ValueError):
            resultado.transicionar(Estado.EXECUTANDO)

    def test_configuracao_rejeita_limites_invalidos(self):
        for opcoes in ({"contexto": 0}, {"timeout": float("inf")},
                       {"timeout": float("nan")}, {"timeout": True},
                       {"limite_chamadas": -1}, {"modelo_economico": ""},
                       {"modelo_economico": None}, {"limite_resposta": "80"}):
            with self.subTest(opcoes=opcoes), self.assertRaises(ValueError):
                Configuracao(**opcoes)

    def test_configuracao_por_ambiente_e_precedencia_do_modelo_explicito(self):
        with patch.dict("os.environ", {
            "LUCIOS_MODELO": "pequeno", "LUCIOS_MODELO_COMPLEXO": "grande:8b",
            "LUCIOS_CONTEXTO": "2048", "LUCIOS_LIMITE_RESPOSTA": "256",
            "LUCIOS_TIMEOUT": "25",
        }):
            config = Configuracao.do_ambiente()
            self.assertEqual(config.modelo_economico, "pequeno")
            self.assertEqual(config.modelo_complexo, "grande:8b")
            self.assertEqual(config.contexto, 2048)
            self.assertEqual(config.limite_resposta, 256)
            self.assertEqual(config.timeout, 25)
            self.assertEqual(Configuracao.do_ambiente("explicito").modelo_economico, "explicito")


if __name__ == "__main__":
    unittest.main()
