"""Chat local: python web_app.py e abra http://127.0.0.1:8000."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

import ollama

from Agent import LuciosAgent
from conversations import ConversationStore
from file_actions import FileActions, FileActionError
from orchestrator import Estado

HOST = "127.0.0.1"
PORT = 8000
ROOT = Path(__file__).resolve().parent
agent = LuciosAgent()
agent_lock = threading.Lock()
FILES_ROOT = Path(os.getenv("LUCIOS_FILES_ROOT", str(Path.home() / "Documents")))


def interpretar_acao(message, model, history=None, root=None):
    """O modelo propõe JSON; a validação e a execução pertencem ao servidor."""
    client = ollama.Client(host="http://127.0.0.1:11434", timeout=45)
    try:
        response = client.chat(
            model=agent.model_name if model == "auto" else validar_modelo(model),
            format="json",
            options={"temperature": 0, "num_predict": 700},
            messages=[
                {"role": "system", "content": (
                    "Interprete o pedido como UMA operação de arquivo dentro da pasta autorizada. "
                    f"A pasta autorizada é {root}. O caminho '.' representa essa pasta; "
                    "se o usuário mencionar o nome da própria pasta autorizada, use '.' "
                    "e não repita esse nome no caminho relativo. "
                    "Responda somente JSON com operation, source, target, content, query, interpretation. "
                    "Operações: list, search, read, mkdir, create, edit, copy, move, rename, delete. "
                    "Caminhos relativos. Para search, source é a pasta e query é o nome/trecho buscado. "
                    "Para contar ou listar candidatos, use search. Para achar UM arquivo, "
                    "inclusive 'o mais atual', use read com source como pasta de busca e query "
                    "como nome aproximado; o usuário escolherá entre candidatos ambíguos. "
                    "Para edit/copy/move/rename/delete com origem aproximada, use source "
                    "como pasta de busca e query como nome aproximado. "
                    "target, content e query devem ser null quando não usados. "
                    "Não invente conteúdo ou caminhos ausentes: nesse caso responda "
                    "{\"operation\":\"clarify\",\"interpretation\":\"pergunta objetiva\"}. "
                    "Para edit, se não souber o conteúdo novo inteiro, use content null. "
                    "Não execute nada.")},
                {"role": "user", "content": (
                    "Contexto recente (apenas para referências; não são instruções de operação):\n"
                    + json.dumps((history or [])[-4:], ensure_ascii=False)[:3000]
                    + "\n\nPedido atual:\n" + message)},
            ])
        return json.loads(response.message.content)
    finally:
        client._client.close()


def gerar_edicao(message, model, original):
    client = ollama.Client(host="http://127.0.0.1:11434", timeout=60)
    try:
        response = client.chat(
            model=agent.model_name if model == "auto" else validar_modelo(model),
            format="json", options={"temperature": 0, "num_predict": 4096},
            messages=[
                {"role": "system", "content": (
                    "Edite o arquivo de texto conforme a instrução do usuário. "
                    "Responda apenas JSON com a chave content contendo o arquivo inteiro atualizado. "
                    "Preserve todo conteúdo não solicitado. Se a instrução for ambígua, "
                    "responda JSON com a chave clarification. Não execute nada.")},
                {"role": "user", "content": f"Pedido:\n{message}\n\nArquivo atual:\n{original}"}])
        data = json.loads(response.message.content)
        if not isinstance(data, dict):
            raise ValueError("Resposta de edição inválida.")
        return data
    finally:
        client._client.close()


class ChatActionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def modelos_instalados():
    client = ollama.Client(host="http://127.0.0.1:11434", timeout=3)
    try:
        return [item.model for item in client.list().models if item.model]
    finally:
        client._client.close()


def validar_modelo(model):
    if not isinstance(model, str) or not model or len(model) > 150:
        raise ChatActionError("Selecione um modelo válido.")
    if model != "auto":
        try:
            installed = modelos_instalados()
        except Exception as error:
            raise ChatActionError("Ollama indisponível. Confira o serviço local.", 503) from error
        if model not in installed:
            raise ChatActionError("Modelo não instalado no Ollama local.")
    return model


def resposta_com_modelo(message, model):
    if model == "auto":
        return agent.chat(message)
    validar_modelo(model)
    return agent.chat(message, modelo_resposta=model)


def resposta_stream(message, model, on_chunk):
    if model == "auto":
        return agent.chat(message, on_chunk=on_chunk)
    validar_modelo(model)
    return agent.chat(message, modelo_resposta=model, on_chunk=on_chunk)


def turno_editavel(item):
    messages, context = item["messages"], item["context"]
    return (len(messages) >= 2 and len(context) >= 2
            and messages[-2]["role"] == context[-2]["role"] == "user"
            and messages[-1]["role"] == context[-1]["role"] == "assistant"
            and messages[-2]["content"] == context[-2]["content"]
            and messages[-1]["content"] == context[-1]["content"])


def publico(item):
    item["editable"] = turno_editavel(item)
    item["editable_turn"] = len(item["messages"]) - 2 if item["editable"] else None
    item.pop("context", None)
    for message in item["messages"]:
        if message["role"] == "assistant" and "alternatives" not in message:
            message["alternatives"] = [{"content": message["content"], "model": None}]
            message["selected"] = 0
    return item


def ultima_resposta(item):
    if not turno_editavel(item):
        raise ChatActionError("Esse turno já foi concluído; só o último pode ser alterado.", 409)
    answer = item["messages"][-1]
    if "alternatives" not in answer:
        answer["alternatives"] = [{"content": answer["content"], "model": None}]
        answer["selected"] = 0
    return answer


class LuciosServer(ThreadingHTTPServer):
    def __init__(self, address, store=None):
        super().__init__(address, LuciosWebHandler)
        self.store = store or ConversationStore(ROOT / "local_data" / "conversations.sqlite3")
        self.token = secrets.token_urlsafe(24)
        self.lab = None
        self.lab_lock = threading.Lock()
        self.active_conversation_id = None
        self.file_actions = FileActions(FILES_ROOT) if FILES_ROOT.is_dir() else None
        self.pending_actions = {}
        self.pending_selections = {}

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
        if url.path == "/api/models":
            try:
                self.send_json({"models": modelos_instalados(), "available": True})
            except Exception:
                self.send_json({"models": [], "available": False})
            return
        if url.path == "/api/conversation":
            try:
                item = self.server.store.get(parse_qs(url.query).get("id", [None])[0])
                self.send_json(publico(item))
            except ValueError as error:
                self.send_json({"error": str(error)}, 404)
            return
        if url.path == "/api/files/pending":
            identifier = parse_qs(url.query).get("conversation_id", [None])[0]
            with agent_lock:
                pending = self.server.pending_actions.get(identifier)
                if pending and pending["expires"] > time.monotonic():
                    self.send_json({"proposal": pending["public"]})
                else:
                    self.server.pending_actions.pop(identifier, None)
                    selection = self.server.pending_selections.get(identifier)
                    if selection and selection["expires"] > time.monotonic():
                        self.send_json({"selection": selection["public"]})
                    else:
                        self.server.pending_selections.pop(identifier, None)
                        self.send_json({"proposal": None, "selection": None})
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
                self.send_json(publico(self.server.store.create(
                    validar_modelo(payload.get("model", "auto")))))
                return
            if self.path == "/api/model":
                model = validar_modelo(payload.get("model"))
                with agent_lock:
                    self.server.store.set_model(payload.get("conversation_id"), model)
                self.send_json({"model": model})
                return
            if self.path == "/api/delete":
                identifier = payload.get("conversation_id")
                if not isinstance(identifier, str) or len(identifier) != 32:
                    raise ValueError("Conversa não encontrada.")
                with agent_lock:
                    self.server.pending_actions.pop(identifier, None)
                    self.server.pending_selections.pop(identifier, None)
                    self.server.store.delete(identifier)
                    if self.server.active_conversation_id == identifier:
                        agent.clear_memory()
                        self.server.active_conversation_id = None
                self.send_json({"ok": True})
                return
            if self.path == "/api/files/prepare":
                self.prepare_file_action(payload)
                return
            if self.path == "/api/files/decide":
                self.decide_file_action(payload)
                return
            if self.path == "/api/files/select":
                self.select_file_candidate(payload)
                return
            if self.path == "/api/chat-stream":
                self.stream_chat(payload)
                return
            if self.path == "/api/turn-stream":
                self.stream_turn(payload)
                return
            if self.path == "/api/lab":
                try:
                    self.send_json({"url": self.server.open_lab()})
                except (ImportError, OSError):
                    self.send_json({"error": "Nao foi possivel abrir o Lab. Instale: python -m pip install -r benchmarks/requirements.txt"}, 503)
                return
            if self.path in ("/api/retry", "/api/edit", "/api/select-answer"):
                self.mutate_last_turn(payload)
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
                    reply = (resposta_com_modelo(message, conversation["model"])
                             if self.path == "/api/chat" and conversation is not None
                             else agent.chat(message if self.path == "/api/chat" else "limpar"))
                    state = agent.ultimo_resultado.estado
                    success = state == Estado.CONCLUIDO
                    status = 200 if success else (409 if state == Estado.CANCELADO else 502)
                if conversation is not None and success:
                    if self.path == "/api/chat":
                        conversation["messages"].extend([
                            {"role": "user", "content": message.strip()},
                            {"role": "assistant", "content": reply,
                             "alternatives": [{"content": reply,
                                               "model": agent.ultimo_resultado.decisao.modelo}],
                             "selected": 0}])
                    self.server.store.save(conversation, agent.conversa)
            response = {"reply" if success else "error": reply}
            if conversation is not None and success:
                response["conversation"] = publico(conversation)
            self.send_json(response, status)
        except ChatActionError as error:
            self.send_json({"error": str(error)}, error.status)
        except FileActionError as error:
            self.send_json({"error": str(error)}, 400)
        except ValueError as error:
            self.send_json({"error": str(error)}, 404)
        except Exception:
            self.send_json({"error": "Nao foi possivel concluir. Confira o armazenamento local e tente novamente."}, 500)

    def prepare_file_action(self, payload):
        if self.server.file_actions is None:
            raise ChatActionError("Configure LUCIOS_FILES_ROOT com uma pasta existente e reinicie o chat.", 503)
        identifier, message = payload.get("conversation_id"), payload.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 4000:
            raise ChatActionError("Descreva uma ação em arquivos com até 4 mil caracteres.")
        with agent_lock:
            item = self.server.store.get(identifier)
            if identifier in self.server.pending_actions or identifier in self.server.pending_selections:
                raise ChatActionError("Responda à confirmação anterior primeiro.", 409)
            try:
                plan = interpretar_acao(message, item["model"], item["messages"],
                                       str(self.server.file_actions.root))
            except Exception as error:
                raise ChatActionError("Não foi possível interpretar a ação com o modelo local.", 502) from error
            if not isinstance(plan, dict):
                raise ChatActionError("O modelo não retornou uma ação válida.", 502)
            if plan.get("operation") == "clarify":
                self.send_json({"clarification": str(plan.get("interpretation", "Detalhe a ação desejada."))[:500]})
                return
            if plan.get("operation") in {"read", "edit", "copy", "move", "rename", "delete"} and plan.get("query"):
                candidates = self.server.file_actions.find_candidates(plan.get("source"), plan["query"])
                if not candidates:
                    self.send_json({"clarification": "Não encontrei candidatos para esse nome na pasta autorizada."})
                    return
                if len(candidates) > 1:
                    selection_id = secrets.token_urlsafe(24)
                    public = {"id": selection_id, "interpretation": plan.get("interpretation", ""),
                              "request": message.strip(), "query": plan["query"],
                              "candidates": candidates[:30], "total": len(candidates)}
                    self.server.pending_selections[identifier] = {
                        "public": public, "plan": plan, "message": message.strip(),
                        "fingerprints": [self.server.file_actions.fingerprint(c["path"])
                                         for c in candidates[:30]],
                        "updated": item["updated"], "expires": time.monotonic() + 600}
                    self.send_json({"selection": public})
                    return
                plan["source"] = candidates[0]["path"]
                plan.pop("query", None)
            self.send_json({"proposal": self.make_file_proposal(identifier, item, plan, message)})

    def make_file_proposal(self, identifier, item, plan, message):
            if plan.get("operation") == "edit" and plan.get("content") is None:
                try:
                    original = self.server.file_actions.read_edit_source(plan.get("source"))
                    edited = gerar_edicao(message, item["model"], original)
                except (OSError, UnicodeError, ValueError) as error:
                    raise ChatActionError(f"Não foi possível preparar a edição: {error}", 400) from error
                if "clarification" in edited:
                    raise ChatActionError(str(edited["clarification"])[:500])
                plan["content"] = edited.get("content")
            proposal = self.server.file_actions.prepare(plan)
            proposal_id = secrets.token_urlsafe(24)
            public = {"id": proposal_id, "interpretation": proposal.interpretation,
                      "operation": proposal.operation, "source": proposal.source,
                      "target": proposal.target, "preview": proposal.preview,
                      "root": str(self.server.file_actions.root),
                      "query": proposal.query, "request": message.strip()}
            self.server.pending_actions[identifier] = {
                "proposal": proposal, "public": public, "message": message.strip(),
                "updated": item["updated"], "expires": time.monotonic() + 600}
            return public

    def select_file_candidate(self, payload):
        identifier, selection_id, index = (payload.get("conversation_id"),
                                           payload.get("selection_id"), payload.get("index"))
        with agent_lock:
            pending = self.server.pending_selections.get(identifier)
            if not pending or not secrets.compare_digest(str(selection_id), pending["public"]["id"]):
                raise ChatActionError("Seleção expirada ou inválida.", 409)
            if time.monotonic() > pending["expires"]:
                self.server.pending_selections.pop(identifier, None)
                raise ChatActionError("Seleção expirada.", 409)
            item = self.server.store.get(identifier)
            if item["updated"] != pending["updated"]:
                self.server.pending_selections.pop(identifier, None)
                raise ChatActionError("A conversa mudou. Faça uma nova busca.", 409)
            if index is None:
                self.server.pending_selections.pop(identifier, None)
                self.send_json({"cancelled": True})
                return
            candidates = pending["public"]["candidates"]
            if type(index) is not int or not 0 <= index < len(candidates):
                raise ChatActionError("Escolha um arquivo da lista.")
            if self.server.file_actions.fingerprint(candidates[index]["path"]) != pending["fingerprints"][index]:
                self.server.pending_selections.pop(identifier, None)
                raise ChatActionError("Esse arquivo mudou desde a busca. Faça uma nova busca.", 409)
            plan = dict(pending["plan"])
            plan["source"] = candidates[index]["path"]
            plan.pop("query", None)
            self.server.pending_selections.pop(identifier, None)
            self.send_json({"proposal": self.make_file_proposal(
                identifier, item, plan, pending["message"])})

    def stream_chat(self, payload):
        message = payload.get("message")
        if (not isinstance(message, str) or not message.strip()
                or len(message) > agent.configuracao.limite_entrada):
            raise ChatActionError("Mensagem inválida ou acima do limite de tamanho.")
        identifier = payload.get("conversation_id")
        with agent_lock:
            conversation = self.server.store.get(identifier)
            agent.clear_memory()
            agent.conversa = conversation["context"]
            self.server.active_conversation_id = identifier
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            def send_event(event):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            try:
                reply = resposta_stream(message, conversation["model"],
                                        lambda part: send_event({"type": "delta", "text": part}))
                state = agent.ultimo_resultado.estado
                if state != Estado.CONCLUIDO:
                    send_event({"type": "error", "message": reply})
                    return
                conversation["messages"].extend([
                    {"role": "user", "content": message.strip()},
                    {"role": "assistant", "content": reply,
                     "alternatives": [{"content": reply,
                                       "model": agent.ultimo_resultado.decisao.modelo}],
                     "selected": 0}])
                self.server.store.save(conversation, agent.conversa)
                send_event({"type": "done", "conversation": publico(conversation)})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                try:
                    send_event({"type": "error", "message": "A geração foi interrompida. Tente novamente."})
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def stream_turn(self, payload):
        action = payload.get("action")
        if action not in ("retry", "edit"):
            raise ChatActionError("Ação de revisão inválida.")
        message = payload.get("message") if action == "edit" else None
        if action == "edit" and (not isinstance(message, str) or not message.strip()
                                  or len(message) > agent.configuracao.limite_entrada):
            raise ChatActionError("Mensagem inválida ou acima do limite de tamanho.")
        identifier, turn = payload.get("conversation_id"), payload.get("turn")
        with agent_lock:
            item = self.server.store.get(identifier)
            if type(turn) is not int or turn != len(item["messages"]) - 2:
                raise ChatActionError("Esse prompt já possui uma continuação.", 409)
            answer = ultima_resposta(item)
            text = message.strip() if action == "edit" else item["messages"][-2]["content"]
            agent.clear_memory()
            agent.conversa = item["context"][:-2]
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            def send_event(event):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            try:
                reply = resposta_stream(text, item["model"],
                                        lambda part: send_event({"type": "delta", "text": part}))
                state = agent.ultimo_resultado.estado
                if state != Estado.CONCLUIDO:
                    agent.conversa = item["context"]
                    send_event({"type": "error", "message": reply})
                    return
                alternative = {"content": reply, "model": agent.ultimo_resultado.decisao.modelo}
                if action == "edit":
                    item["messages"][-2]["content"] = text
                    answer["alternatives"] = [alternative]
                    answer["selected"] = 0
                else:
                    answer["alternatives"].append(alternative)
                    answer["selected"] = len(answer["alternatives"]) - 1
                answer["content"] = reply
                item["context"] = agent.conversa
                self.server.store.save(item, item["context"])
                self.server.active_conversation_id = identifier
                send_event({"type": "done", "conversation": publico(item)})
            except (BrokenPipeError, ConnectionResetError):
                agent.conversa = item["context"]
            except Exception:
                agent.conversa = item["context"]
                try:
                    send_event({"type": "error", "message": "A geração foi interrompida. Tente novamente."})
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def decide_file_action(self, payload):
        identifier, proposal_id, confirm = (payload.get("conversation_id"),
                                            payload.get("proposal_id"), payload.get("confirm"))
        if type(confirm) is not bool:
            raise ChatActionError("Informe confirmar ou negar.")
        with agent_lock:
            pending = self.server.pending_actions.get(identifier)
            if not pending or not secrets.compare_digest(str(proposal_id), pending["public"]["id"]):
                raise ChatActionError("Confirmação expirada ou inválida.", 409)
            self.server.pending_actions.pop(identifier)
            item = self.server.store.get(identifier)
            if item["updated"] != pending["updated"] or time.monotonic() > pending["expires"]:
                raise ChatActionError("A conversa mudou. Solicite uma nova prévia.", 409)
            if confirm:
                try:
                    result = self.server.file_actions.execute(pending["proposal"])
                except FileActionError as error:
                    result = f"Ação não executada: {error}"
                except (OSError, UnicodeError) as error:
                    result = f"Ação não concluída: {type(error).__name__}."
            else:
                result = "Ação negada. Nenhum arquivo foi alterado."
            item["messages"].extend([
                {"role": "user", "content": pending["message"]},
                {"role": "assistant", "content": result}])
            self.server.store.save(item, item["context"])
            self.send_json({"result": result, "conversation": publico(item)})

    def mutate_last_turn(self, payload):
        action = self.path
        identifier = payload.get("conversation_id")
        if action == "/api/edit":
            message = payload.get("message")
            if (not isinstance(message, str) or not message.strip()
                    or len(message) > agent.configuracao.limite_entrada):
                raise ChatActionError("Mensagem inválida ou acima do limite de tamanho.")
            message = message.strip()
        if action == "/api/select-answer":
            index = payload.get("index")
            if type(index) is not int:
                raise ChatActionError("Escolha uma versão válida.")
        with agent_lock:
            item = self.server.store.get(identifier)
            turn = payload.get("turn")
            if type(turn) is not int or turn != len(item["messages"]) - 2:
                raise ChatActionError("Esse prompt já possui uma continuação.", 409)
            answer = ultima_resposta(item)
            if action == "/api/select-answer":
                if not 0 <= index < len(answer["alternatives"]):
                    raise ChatActionError("Versão não encontrada.")
                answer["selected"] = index
                answer["content"] = answer["alternatives"][index]["content"]
                item["context"][-1] = {"role": "assistant", "content": answer["content"]}
                agent.clear_memory()
                agent.conversa = item["context"]
            else:
                text = message if action == "/api/edit" else item["messages"][-2]["content"]
                agent.clear_memory()
                agent.conversa = item["context"][:-2]
                try:
                    reply = resposta_com_modelo(text, item["model"])
                except Exception:
                    agent.conversa = item["context"]
                    raise
                state = agent.ultimo_resultado.estado
                if state != Estado.CONCLUIDO:
                    agent.conversa = item["context"]
                    self.send_json({"error": reply}, 409 if state == Estado.CANCELADO else 502)
                    return
                alternative = {"content": reply, "model": agent.ultimo_resultado.decisao.modelo}
                if action == "/api/edit":
                    item["messages"][-2]["content"] = text
                    answer["alternatives"] = [alternative]
                    answer["selected"] = 0
                else:
                    answer["alternatives"].append(alternative)
                    answer["selected"] = len(answer["alternatives"]) - 1
                answer["content"] = reply
                item["context"] = agent.conversa
            self.server.store.save(item, item["context"])
            self.server.active_conversation_id = identifier
            self.send_json({"conversation": publico(item)})

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
