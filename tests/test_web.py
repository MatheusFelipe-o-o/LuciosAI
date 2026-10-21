from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from threading import Thread
import unittest
from unittest.mock import Mock, patch

from Agent import LuciosAgent
from orchestrator import Configuracao, Estado, Resultado
import web_app


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), web_app.LuciosWebHandler)
        cls.thread = Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.cliente = Mock()
        self.cliente.chat.return_value = {"message": {"content": "**Resposta**"}}
        self.agent = LuciosAgent(configuracao=Configuracao(), cliente=self.cliente)
        self.agent.memory_manager = Mock()
        self.patch = patch.object(web_app, "agent", self.agent)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def post(self, rota="/api/chat", corpo=None, bruto=None):
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=3)
        self.addCleanup(conn.close)
        texto = bruto if bruto is not None else json.dumps(corpo or {})
        conn.request("POST", rota, texto.encode("utf-8"), {"Content-Type": "application/json"})
        resposta = conn.getresponse()
        return resposta.status, json.loads(resposta.read())

    def test_chat_atravessa_interface_orquestrador_e_cliente(self):
        status, data = self.post(corpo={"message": "Olá"})
        self.assertEqual(status, 200)
        self.assertEqual(data["reply"], "**Resposta**")
        self.assertEqual(self.agent.ultimo_resultado.estado, Estado.CONCLUIDO)
        self.cliente.chat.assert_called_once()

    def test_json_invalido_e_payload_que_nao_seja_objeto(self):
        for texto in ("[]", "null", "{", "12"):
            with self.subTest(texto=texto):
                self.assertEqual(self.post(bruto=texto)[0], 400)
        self.cliente.chat.assert_not_called()

    def test_mensagem_de_tipo_errado_ou_grande(self):
        for valor in ([], {}, 123, None, "", "a" * 16001):
            with self.subTest(tipo=type(valor).__name__):
                self.assertEqual(self.post(corpo={"message": valor})[0], 400)
        self.cliente.chat.assert_not_called()

    def test_falha_de_modelo_nao_retorna_http_de_sucesso(self):
        self.cliente.chat.side_effect = RuntimeError("offline")
        status, data = self.post(corpo={"message": "Olá"})
        self.assertEqual(status, 502)
        self.assertIn("error", data)
        self.assertEqual(self.agent.conversa, [])

    def test_limpar_via_http_sem_chamada_ao_modelo(self):
        self.agent.conversa = [{"role": "user", "content": "exemplo"}]
        self.assertEqual(self.post(rota="/api/clear")[0], 200)
        self.assertEqual(self.agent.conversa, [])
        self.assertEqual(self.agent.ultimo_resultado.chamadas_modelo, 0)
        self.cliente.chat.assert_not_called()

    def test_tamanho_do_corpo_invalido_e_recusado_antes_da_leitura(self):
        handler = object.__new__(web_app.LuciosWebHandler)
        handler.rfile = io.BytesIO(b"{}")
        for tamanho in ("-1", "0", "65537", "invalido"):
            handler.headers = {"Content-Length": tamanho}
            with self.subTest(tamanho=tamanho), self.assertRaises(ValueError):
                handler.read_json()
        self.assertEqual(handler.rfile.tell(), 0)

    def test_falha_ao_limpar_nao_retorna_sucesso(self):
        self.agent.ultimo_resultado = Resultado(estados=[Estado.FALHOU], erro="tempo")
        with patch.object(self.agent, "chat", return_value="Erro de execução"):
            status, data = self.post(rota="/api/clear")
        self.assertEqual(status, 502)
        self.assertIn("error", data)

    def test_limpar_e_encerrar_validam_e_consumem_json(self):
        for rota in ("/api/clear", "/api/end"):
            with self.subTest(rota=rota):
                self.assertEqual(self.post(rota=rota, bruto="[]")[0], 400)
                self.assertEqual(self.post(rota=rota, bruto="")[0], 200)


if __name__ == "__main__":
    unittest.main()
