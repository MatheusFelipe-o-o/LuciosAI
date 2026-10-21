from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from threading import Thread
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from Agent import LuciosAgent
from orchestrator import Configuracao, Estado, Resultado
import web_app
from conversations import ConversationStore


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.servidor = web_app.LuciosServer(("127.0.0.1", 0),
                                          ConversationStore(Path(cls.tmp.name) / "history.db"))
        cls.thread = Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def setUp(self):
        self.cliente = Mock()
        self.cliente.chat.return_value = {"message": {"content": "**Resposta**"}}
        self.agent = LuciosAgent(configuracao=Configuracao(), cliente=self.cliente)
        self.agent.memory_manager = Mock()
        self.agent.memory_manager.buscar_memorias.return_value = []
        self.agent.memory_manager.listar_memorias_recentes.return_value = []
        self.patch = patch.object(web_app, "agent", self.agent)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def post(self, rota="/api/chat", corpo=None, bruto=None):
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=3)
        self.addCleanup(conn.close)
        texto = bruto if bruto is not None else json.dumps(corpo or {})
        conn.request("POST", rota, texto.encode("utf-8"), {
            "Content-Type": "application/json", "X-Lucios-Token": self.servidor.token})
        resposta = conn.getresponse()
        return resposta.status, json.loads(resposta.read())

    def get(self, path):
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read()

    def test_assets_e_token_da_pagina(self):
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(self.servidor.token.encode(), html)
        self.assertNotIn(b"__TOKEN__", html)
        for path in ("/app.css", "/app.js", "/markdown.js"):
            self.assertEqual(self.get(path)[0], 200)
        self.assertEqual(self.get("/../Agent.py")[0], 404)

    def test_isola_conversas_e_reabre_contexto(self):
        a = self.post("/api/new")[1]["id"]
        b = self.post("/api/new")[1]["id"]
        for identifier, message in ((a, "Mensagem A"), (b, "Mensagem B"), (a, "Retomar A")):
            self.assertEqual(self.post(corpo={"message": message, "conversation_id": identifier})[0], 200)
        contents = [m["content"] for m in self.cliente.chat.call_args.kwargs["messages"]]
        self.assertIn("Mensagem A", contents)
        self.assertNotIn("Mensagem B", contents)
        loaded = json.loads(self.get("/api/conversation?id=" + a)[1])
        self.assertEqual(len(loaded["messages"]), 4)
        self.assertNotIn("context", loaded)
        self.assertEqual(loaded["title"], "Mensagem A")

    def test_excluir_remove_apenas_escolhida_e_limpa_contexto_ativo(self):
        a = self.post("/api/new")[1]["id"]
        b = self.post("/api/new")[1]["id"]
        self.post(corpo={"message": "Olá", "conversation_id": a})
        self.assertEqual(self.post("/api/delete", {"conversation_id": b})[0], 200)
        self.assertEqual(len(self.agent.conversa), 2)
        self.assertEqual(self.get("/api/conversation?id=" + a)[0], 200)
        self.assertEqual(self.get("/api/conversation?id=" + b)[0], 404)
        self.assertEqual(self.post("/api/delete", {"conversation_id": a})[0], 200)
        self.assertEqual(self.agent.conversa, [])
        self.assertEqual(self.get("/api/conversation?id=" + a)[0], 404)
        self.agent.memory_manager.salvar_memoria.assert_not_called()

    def test_excluir_id_invalido_ou_ausente(self):
        for identifier in (None, [], 123, "' OR 1=1 --", "0" * 32):
            self.assertEqual(self.post("/api/delete", {"conversation_id": identifier})[0], 404)

    def test_excluir_exige_token(self):
        identifier = self.post("/api/new")[1]["id"]
        conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("POST", "/api/delete", json.dumps({"conversation_id": identifier}))
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        self.assertEqual(self.get("/api/conversation?id=" + identifier)[0], 200)

    def test_modelo_por_conversa_e_catalogo_validado(self):
        with patch.object(web_app, "modelos_instalados", return_value=["small:latest", "large:latest"]):
            self.assertEqual(json.loads(self.get("/api/models")[1])["models"],
                             ["small:latest", "large:latest"])
            identifier = self.post("/api/new", {"model": "large:latest"})[1]["id"]
            self.assertEqual(self.post(corpo={"message": "Olá", "conversation_id": identifier})[0], 200)
            self.assertEqual(self.cliente.chat.call_args.kwargs["model"], "large:latest")
            self.assertEqual(self.servidor.store.get(identifier)["model"], "large:latest")
            self.assertEqual(self.post("/api/model", {"conversation_id": identifier,
                                                        "model": "small:latest"})[0], 200)
            self.assertEqual(self.post("/api/model", {"conversation_id": identifier,
                                                        "model": "inventado:latest"})[0], 400)
            self.assertEqual(self.servidor.store.get(identifier)["model"], "small:latest")

    def test_nova_resposta_navegacao_e_bloqueio_apos_proximo_prompt(self):
        identifier = self.post("/api/new")[1]["id"]
        self.cliente.chat.side_effect = [
            {"message": {"content": "Primeira"}},
            {"message": {"content": "Segunda"}},
            {"message": {"content": "Continuação"}},
        ]
        self.assertEqual(self.post(corpo={"message": "Pergunta", "conversation_id": identifier})[0], 200)
        status, data = self.post("/api/retry", {"conversation_id": identifier, "turn": 0})
        self.assertEqual(status, 200)
        answer = data["conversation"]["messages"][-1]
        self.assertEqual([a["content"] for a in answer["alternatives"]], ["Primeira", "Segunda"])
        self.assertEqual(answer["selected"], 1)
        self.assertEqual(self.post("/api/select-answer", {"conversation_id": identifier,
                                                           "index": 0, "turn": 0})[0], 200)
        self.assertEqual(self.servidor.store.get(identifier)["context"][-1]["content"], "Primeira")
        self.assertEqual(self.post(corpo={"message": "Depois", "conversation_id": identifier})[0], 200)
        sent = [m["content"] for m in self.cliente.chat.call_args.kwargs["messages"]]
        self.assertIn("Primeira", sent)
        self.assertNotIn("Segunda", sent)
        self.assertEqual(self.post("/api/select-answer", {"conversation_id": identifier,
                                                           "index": 0, "turn": 0})[0], 409)
        self.assertEqual(self.post("/api/retry", {"conversation_id": identifier,
                                                 "turn": 0})[0], 409)
        self.assertEqual(self.servidor.store.get(identifier)["messages"][1]["content"], "Primeira")

    def test_edicao_substitui_ultimo_prompt_somente_apos_sucesso(self):
        identifier = self.post("/api/new")[1]["id"]
        self.cliente.chat.return_value = {"message": {"content": "Antiga"}}
        self.post(corpo={"message": "Original", "conversation_id": identifier})
        self.cliente.chat.side_effect = RuntimeError("offline")
        self.assertEqual(self.post("/api/edit", {"conversation_id": identifier,
                                                 "message": "Revisada", "turn": 0})[0], 502)
        self.assertEqual(self.servidor.store.get(identifier)["messages"][-2]["content"], "Original")
        self.cliente.chat.side_effect = None
        self.cliente.chat.return_value = {"message": {"content": "Nova"}}
        status, data = self.post("/api/edit", {"conversation_id": identifier,
                                                "message": "Revisada", "turn": 0})
        self.assertEqual(status, 200)
        self.assertEqual([m["content"] for m in data["conversation"]["messages"][-2:]],
                         ["Revisada", "Nova"])
        self.assertEqual(self.servidor.store.get(identifier)["title"], "Revisada")
        self.assertEqual(self.servidor.store.get(identifier)["context"][-2]["content"], "Revisada")

    def test_historico_legado_oferece_uma_versao_sem_perder_contexto(self):
        item = self.servidor.store.create()
        item["messages"] = [{"role": "user", "content": "Antiga pergunta"},
                            {"role": "assistant", "content": "Antiga resposta"}]
        self.servidor.store.save(item, item["messages"])
        loaded = json.loads(self.get("/api/conversation?id=" + item["id"])[1])
        self.assertEqual(loaded["model"], "auto")
        self.assertEqual(loaded["messages"][-1]["alternatives"][0]["content"], "Antiga resposta")
        self.assertEqual(loaded["editable_turn"], 0)
        self.assertEqual(self.post("/api/retry", {"conversation_id": item["id"],
                                                 "turn": 0})[0], 200)
        self.assertEqual(len(self.servidor.store.get(item["id"])["messages"][-1]["alternatives"]), 2)

    def test_modelo_retirado_nao_substitui_resposta_anterior(self):
        with patch.object(web_app, "modelos_instalados", return_value=["small:latest"]):
            identifier = self.post("/api/new", {"model": "small:latest"})[1]["id"]
        self.cliente.chat.return_value = {"message": {"content": "Resposta segura"}}
        with patch.object(web_app, "modelos_instalados", return_value=["small:latest"]):
            self.post(corpo={"message": "Pergunta", "conversation_id": identifier})
        with patch.object(web_app, "modelos_instalados", return_value=[]):
            self.assertEqual(self.post("/api/retry", {"conversation_id": identifier,
                                                     "turn": 0})[0], 400)
        saved = self.servidor.store.get(identifier)
        self.assertEqual(saved["messages"][-1]["content"], "Resposta segura")
        self.assertEqual(len(saved["messages"][-1]["alternatives"]), 1)

    def test_falha_nao_entra_no_historico(self):
        identifier = self.post("/api/new")[1]["id"]
        self.cliente.chat.side_effect = RuntimeError("offline")
        self.assertEqual(self.post(corpo={"message": "Teste", "conversation_id": identifier})[0], 502)
        self.assertEqual(self.servidor.store.get(identifier)["messages"], [])

    def test_conversa_invalida_nao_chama_modelo(self):
        self.assertEqual(self.post(corpo={"message": "Teste", "conversation_id": "inexistente"})[0], 404)
        self.cliente.chat.assert_not_called()

    def test_host_origem_e_token(self):
        for headers in ({}, {"X-Lucios-Token": self.servidor.token, "Origin": "https://example.com"},
                        {"X-Lucios-Token": self.servidor.token, "Host": "example.com"}):
            conn = HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=3)
            self.addCleanup(conn.close)
            conn.request("POST", "/api/new", b"{}", headers)
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

    def test_lab_inicia_uma_vez_e_serve_painel(self):
        first = self.post("/api/lab")[1]["url"]
        self.assertEqual(self.post("/api/lab")[1]["url"], first)
        port = int(first.rsplit(":", 1)[1])
        conn = HTTPConnection("127.0.0.1", port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b"Performance Lab", response.read())

    def test_salvar_memoria_preserva_transcricao_e_limpa_contexto(self):
        identifier = self.post("/api/new")[1]["id"]
        self.post(corpo={"message": "Conversa para salvar", "conversation_id": identifier})
        self.agent.memory_manager.criar_memoria.return_value = {"titulo": "Exemplo"}
        self.assertEqual(self.post("/api/end", {"conversation_id": identifier})[0], 200)
        data = self.servidor.store.get(identifier)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["context"], [])

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
