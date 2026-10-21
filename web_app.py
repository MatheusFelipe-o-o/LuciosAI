"""Chat local: python web_app.py e abra http://127.0.0.1:8000."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from Agent import LuciosAgent
from conversations import ConversationStore
from orchestrator import Estado

HOST = "127.0.0.1"
PORT = 8000
ROOT = Path(__file__).resolve().parent
agent = LuciosAgent()
agent_lock = threading.Lock()


class LuciosServer(ThreadingHTTPServer):
    def __init__(self, address, store=None):
        super().__init__(address, LuciosWebHandler)
        self.store = store or ConversationStore(ROOT / "local_data" / "conversations.sqlite3")
        self.token = secrets.token_urlsafe(24)
        self.lab = None
        self.lab_lock = threading.Lock()
        self.active_conversation_id = None

    def open_lab(self):
        # Optional package: chat works without benchmark dependencies.
        with self.lab_lock:
            if self.lab is None:
                from benchmarks.web import criar_servidor
                self.lab = criar_servidor(porta=0)
                threading.Thread(target=self.lab.serve_forever, daemon=True).start()
            return f"http://127.0.0.1:{self.lab.server_port}"

    def server_close(self):
        if self.lab is not None:
            self.lab.shutdown()
            self.lab.server_close()
            self.lab.painel.fechar()
        super().server_close()


class LuciosWebHandler(BaseHTTPRequestHandler):
    def authorized(self, mutation=False):
        authority = f"{HOST}:{self.server.server_port}"
        if self.headers.get("Host") != authority:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{authority}":
            return False
        return not mutation or secrets.compare_digest(
            self.headers.get("X-Lucios-Token", ""), self.server.token)

    def do_GET(self):
        if not self.authorized():
            self.send_json({"error": "Origem nao autorizada."}, 403)
            return
        url = urlsplit(self.path)
        assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                  "/app.css": ("app.css", "text/css"), "/app.js": ("app.js", "text/javascript"),
                  "/markdown.js": ("markdown.js", "text/javascript")}
        if url.path in assets:
            name, mime = assets[url.path]
            content = (ROOT / "web" / name).read_text(encoding="utf-8")
            if mime == "text/html":
                content = content.replace("__TOKEN__", self.server.token)
            self.send_content(content.encode("utf-8"), mime + "; charset=utf-8")
            return
        if url.path == "/api/conversations":
            self.send_json({"conversations": self.server.store.list(), "model": agent.model_name})
            return
        if url.path == "/api/conversation":
            try:
                item = self.server.store.get(parse_qs(url.query).get("id", [None])[0])
                item.pop("context")
                self.send_json(item)
            except ValueError as error:
                self.send_json({"error": str(error)}, 404)
            return
        self.send_json({"error": "Rota nao encontrada."}, 404)

    def do_POST(self):
        if not self.authorized(mutation=True):
            size = self.headers.get("Content-Length", "0")
            if size.isdigit() and 0 < int(size) <= 65536:
                self.rfile.read(int(size))
            self.send_json({"error": "Solicitacao nao autorizada."}, 403)
            return
        try:
            payload = self.read_json() if self.headers.get("Content-Length", "0") != "0" else {}
        except (ValueError, UnicodeDecodeError):
            self.send_json({"error": "Envie um objeto JSON valido de ate 64 KiB."}, 400)
            return
        try:
            if self.path == "/api/new":
                self.send_json(self.server.store.create())
                return
            if self.path == "/api/delete":
                identifier = payload.get("conversation_id")
                with agent_lock:
                    self.server.store.delete(identifier)
                    if self.server.active_conversation_id == identifier:
                        agent.clear_memory()
                        self.server.active_conversation_id = None
                self.send_json({"ok": True})
                return
            if self.path == "/api/lab":
                try:
                    self.send_json({"url": self.server.open_lab()})
                except (ImportError, OSError):
                    self.send_json({"error": "Nao foi possivel abrir o Lab. Instale: python -m pip install -r benchmarks/requirements.txt"}, 503)
                return
            if self.path not in ("/api/chat", "/api/clear", "/api/end"):
                self.send_json({"error": "Rota nao encontrada."}, 404)
                return
            message = payload.get("message", "")
            if self.path == "/api/chat" and (
                not isinstance(message, str) or not message.strip()
                or len(message) > agent.configuracao.limite_entrada
            ):
                self.send_json({"error": "Mensagem invalida ou acima do limite de tamanho."}, 400)
                return
            with agent_lock:
                conversation = None
                if "conversation_id" in payload:
                    conversation = self.server.store.get(payload["conversation_id"])
                    agent.clear_memory()
                    agent.conversa = conversation["context"]
                    self.server.active_conversation_id = conversation["id"]
                if self.path == "/api/end":
                    reply = agent.end_conversation()
                    success = agent.estado_encerramento != "falhou"
                    status = 200 if success else 502
                else:
                    reply = agent.chat(message if self.path == "/api/chat" else "limpar")
                    state = agent.ultimo_resultado.estado
                    success = state == Estado.CONCLUIDO
                    status = 200 if success else (409 if state == Estado.CANCELADO else 502)
                if conversation is not None and success:
                    if self.path == "/api/chat":
                        conversation["messages"].extend([
                            {"role": "user", "content": message.strip()},
                            {"role": "assistant", "content": reply}])
                    self.server.store.save(conversation, agent.conversa)
            self.send_json({"reply" if success else "error": reply}, status)
        except ValueError as error:
            self.send_json({"error": str(error)}, 404)
        except Exception:
            self.send_json({"error": "Nao foi possivel concluir. Confira o armazenamento local e tente novamente."}, 500)

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if not 0 < content_length <= 65536:
            raise ValueError("Tamanho de JSON invalido.")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("O JSON deve ser um objeto.")
        return payload

    def send_content(self, encoded, mime, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload, status=200):
        self.send_content(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8", status)

    def log_message(self, format, *args):
        return


def run():
    server = LuciosServer((HOST, PORT))
    print(f"Lucios web rodando em http://{HOST}:{PORT}", flush=True)
    print("Pressione Ctrl+C para parar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
