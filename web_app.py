from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError
import json
import threading

from Agent import LuciosAgent


HOST = "127.0.0.1"
PORT = 8000

agent = LuciosAgent()
agent_lock = threading.Lock()


HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Lucios</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07030d;
      --bg-2: #12071e;
      --panel: rgba(17, 7, 30, 0.84);
      --panel-strong: rgba(25, 10, 42, 0.94);
      --line: rgba(255, 255, 255, 0.72);
      --line-soft: rgba(255, 255, 255, 0.18);
      --text: #f7f2ff;
      --muted: #c8bdd7;
      --accent: #9b5cff;
      --accent-2: #d6c2ff;
      --danger: #ff7d9f;
      --shadow: rgba(0, 0, 0, 0.38);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px),
        linear-gradient(180deg, rgba(255,255,255,0.035) 1px, transparent 1px),
        radial-gradient(circle at 15% 8%, rgba(133, 76, 255, 0.22), transparent 32%),
        linear-gradient(135deg, var(--bg), var(--bg-2) 52%, #050208);
      background-size: 72px 72px, 72px 72px, auto, auto;
      color: var(--text);
    }

    .app {
      width: min(1120px, calc(100vw - 28px));
      min-height: 100vh;
      margin: 0 auto;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 18px;
      padding: 22px 0;
    }

    .topbar {
      border: 1px solid var(--line);
      background: rgba(7, 3, 13, 0.72);
      box-shadow: 0 22px 60px var(--shadow);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 16px;
      border-radius: 8px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .mark {
      width: 40px;
      height: 40px;
      border: 1px solid var(--line);
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: #10051d;
      box-shadow: inset 0 0 0 1px rgba(155, 92, 255, 0.32);
      font-weight: 800;
      letter-spacing: 0;
    }

    h1 {
      font-size: 18px;
      line-height: 1.15;
      margin: 0;
      letter-spacing: 0;
    }

    .status {
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .actions {
      display: flex;
      gap: 10px;
      align-items: center;
      flex: none;
    }

    button {
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      min-height: 40px;
      padding: 0 14px;
      border-radius: 8px;
      font: inherit;
      cursor: pointer;
      transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
    }

    button:hover {
      border-color: #ffffff;
      background: rgba(255, 255, 255, 0.1);
      transform: translateY(-1px);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.58;
      transform: none;
    }

    .primary {
      background: linear-gradient(135deg, #6f35ff, #9b5cff);
      border-color: rgba(255, 255, 255, 0.86);
      font-weight: 700;
    }

    .chat-shell {
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 24px 80px var(--shadow);
      overflow: hidden;
      display: grid;
      grid-template-rows: 1fr;
      position: relative;
    }

    .chat-shell::before,
    .composer::before {
      content: "";
      position: absolute;
      inset: 10px;
      border: 1px solid var(--line-soft);
      pointer-events: none;
      border-radius: 6px;
    }

    .messages {
      overflow-y: auto;
      padding: 28px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      scroll-behavior: smooth;
    }

    .message {
      width: min(780px, 88%);
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      padding: 13px 14px;
      line-height: 1.65;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      box-shadow: 0 14px 34px rgba(0, 0, 0, 0.18);
    }

    .message .name {
      display: block;
      margin-bottom: 6px;
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }

    .markdown-body > :first-child {
      margin-top: 0;
    }

    .markdown-body > :last-child {
      margin-bottom: 0;
    }

    .markdown-body h1,
    .markdown-body h2,
    .markdown-body h3 {
      margin: 14px 0 7px;
      line-height: 1.3;
    }

    .markdown-body h1 { font-size: 1.2em; }
    .markdown-body h2 { font-size: 1.1em; }
    .markdown-body h3 { font-size: 1em; }

    .markdown-body p {
      margin: 0 0 10px;
    }

    .markdown-body ul,
    .markdown-body ol {
      margin: 6px 0 12px;
      padding-left: 24px;
    }

    .markdown-body li {
      padding-left: 3px;
      margin: 4px 0;
    }

    .markdown-body li ul,
    .markdown-body li ol {
      margin: 3px 0 5px;
    }

    .markdown-body strong {
      color: #fff;
      font-weight: 750;
    }

    .markdown-body code {
      padding: 1px 5px;
      border: 1px solid var(--line-soft);
      border-radius: 4px;
      background: rgba(0, 0, 0, 0.28);
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.92em;
    }

    .assistant {
      align-self: flex-start;
      background: rgba(255, 255, 255, 0.045);
    }

    .user {
      align-self: flex-end;
      background: rgba(105, 49, 232, 0.22);
      border-color: rgba(255, 255, 255, 0.42);
    }

    .system {
      align-self: center;
      max-width: 680px;
      text-align: center;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.035);
    }

    .typing {
      display: inline-flex;
      gap: 5px;
      align-items: center;
    }

    .typing span {
      width: 6px;
      height: 6px;
      border-radius: 999px;
      background: var(--accent-2);
      animation: pulse 900ms infinite ease-in-out;
    }

    .typing span:nth-child(2) {
      animation-delay: 120ms;
    }

    .typing span:nth-child(3) {
      animation-delay: 240ms;
    }

    @keyframes pulse {
      0%, 100% { opacity: 0.35; transform: translateY(0); }
      50% { opacity: 1; transform: translateY(-3px); }
    }

    .composer {
      position: relative;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-strong);
      padding: 14px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      box-shadow: 0 22px 60px var(--shadow);
    }

    textarea {
      width: 100%;
      min-height: 52px;
      max-height: 160px;
      resize: vertical;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.22);
      color: var(--text);
      padding: 14px;
      font: inherit;
      line-height: 1.35;
      outline: none;
    }

    textarea:focus {
      border-color: #ffffff;
      box-shadow: 0 0 0 3px rgba(155, 92, 255, 0.18);
    }

    textarea::placeholder {
      color: rgba(247, 242, 255, 0.52);
    }

    .send {
      min-width: 112px;
      height: 52px;
      align-self: end;
    }

    @media (max-width: 720px) {
      .app {
        width: min(100vw - 18px, 1120px);
        gap: 10px;
        padding: 9px 0;
      }

      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }

      .actions {
        width: 100%;
      }

      .actions button {
        flex: 1;
      }

      .messages {
        padding: 22px 18px;
      }

      .message {
        width: 100%;
      }

      .composer {
        grid-template-columns: 1fr;
      }

      .send {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <header class="topbar">
      <div class="brand">
        <div class="mark" aria-hidden="true">L</div>
        <div>
          <h1>Lucios</h1>
          <div class="status" id="status">Pronto para conversar</div>
        </div>
      </div>
      <div class="actions">
        <button type="button" id="endBtn" title="Salvar conversa na memória">Salvar conversa</button>
        <button type="button" id="clearBtn" title="Limpar conversa">Limpar</button>
      </div>
    </header>

    <section class="chat-shell" aria-label="Chat do Lucios">
      <div class="messages" id="messages">
        <article class="message assistant">
          <span class="name">Lucios</span>
          Ola! Eu sou o Lucios, como posso ajuda-lo hoje?
        </article>
      </div>
    </section>

    <form class="composer" id="chatForm">
      <textarea id="prompt" name="prompt" placeholder="Digite sua mensagem..." autocomplete="off"></textarea>
      <button class="primary send" id="sendBtn" type="submit">Enviar</button>
    </form>
  </main>

  <script>
    const form = document.querySelector("#chatForm");
    const promptInput = document.querySelector("#prompt");
    const messages = document.querySelector("#messages");
    const statusText = document.querySelector("#status");
    const sendBtn = document.querySelector("#sendBtn");
    const endBtn = document.querySelector("#endBtn");
    const clearBtn = document.querySelector("#clearBtn");

    function addMessage(role, name, text) {
      const article = document.createElement("article");
      article.className = `message ${role}`;

      const label = document.createElement("span");
      label.className = "name";
      label.textContent = name;

      const content = document.createElement("div");
      content.className = "markdown-body";
      if (role === "assistant") {
        renderMarkdown(text, content);
      } else {
        content.textContent = text;
      }
      article.append(label, content);
      messages.appendChild(article);
      messages.scrollTop = messages.scrollHeight;
      return article;
    }

    function appendInlineMarkdown(parent, text) {
      const tokenPattern = /(\\*\\*[^*\\n]+?\\*\\*|`[^`\\n]+`|\\*[^*\\n]+?\\*)/g;
      let position = 0;

      for (const match of text.matchAll(tokenPattern)) {
        const token = match[0];
        parent.appendChild(document.createTextNode(text.slice(position, match.index)));

        let element;
        let value;
        if (token.startsWith("**")) {
          element = document.createElement("strong");
          value = token.slice(2, -2);
        } else if (token.startsWith("`")) {
          element = document.createElement("code");
          value = token.slice(1, -1);
        } else {
          element = document.createElement("em");
          value = token.slice(1, -1);
        }
        element.textContent = value;
        parent.appendChild(element);
        position = match.index + token.length;
      }

      parent.appendChild(document.createTextNode(text.slice(position)));
    }

    function createMarkdownList(type) {
      return document.createElement(type === "ordered" ? "ol" : "ul");
    }

    function renderMarkdown(text, container) {
      const lines = text.replace(/\\r\\n?/g, "\\n").split("\\n");
      let index = 0;

      while (index < lines.length) {
        if (!lines[index].trim()) {
          index += 1;
          continue;
        }

        const heading = lines[index].match(/^(#{1,3})\\s+(.+)$/);
        if (heading) {
          const element = document.createElement(`h${heading[1].length}`);
          appendInlineMarkdown(element, heading[2]);
          container.appendChild(element);
          index += 1;
          continue;
        }

        const firstItem = lines[index].match(/^([ \\t]*)([-*+]|\\d+[.)])\\s+(.+)$/);
        if (firstItem) {
          const indentWidth = (value) => value.replace(/\\t/g, "  ").length;
          const firstIndent = indentWidth(firstItem[1]);
          const firstType = /^\d/.test(firstItem[2]) ? "ordered" : "unordered";
          const rootList = createMarkdownList(firstType);
          container.appendChild(rootList);
          const stack = [{
            indent: firstIndent,
            type: firstType,
            list: rootList,
            item: null
          }];

          while (index < lines.length) {
            const item = lines[index].match(/^([ \\t]*)([-*+]|\\d+[.)])\\s+(.+)$/);
            if (!item) break;

            const indent = indentWidth(item[1]);
            const type = /^\d/.test(item[2]) ? "ordered" : "unordered";
            while (stack.length > 1 && indent < stack[stack.length - 1].indent) {
              stack.pop();
            }

            let current = stack[stack.length - 1];
            if (indent === current.indent && type !== current.type) break;

            if (indent > current.indent) {
              if (!current.item) break;
              const nestedList = createMarkdownList(type);
              current.item.appendChild(nestedList);
              current = {
                indent,
                type,
                list: nestedList,
                item: null
              };
              stack.push(current);
            }

            const listItem = document.createElement("li");
            appendInlineMarkdown(listItem, item[3]);
            current.list.appendChild(listItem);
            current.item = listItem;
            index += 1;
          }
          continue;
        }

        const paragraphLines = [];
        while (index < lines.length && lines[index].trim()) {
          if (
            paragraphLines.length > 0 &&
            (/^(#{1,3})\\s+/.test(lines[index]) ||
              /^([ \\t]*)([-*+]|\\d+[.)])\\s+/.test(lines[index]))
          ) {
            break;
          }
          paragraphLines.push(lines[index].trim());
          index += 1;
        }

        if (paragraphLines.length) {
          const paragraph = document.createElement("p");
          appendInlineMarkdown(paragraph, paragraphLines.join(" "));
          container.appendChild(paragraph);
        }
      }
    }

    function addTyping() {
      const article = document.createElement("article");
      article.className = "message assistant";
      article.innerHTML = '<span class="name">Lucios</span><span class="typing" aria-label="Lucios digitando"><span></span><span></span><span></span></span>';
      messages.appendChild(article);
      messages.scrollTop = messages.scrollHeight;
      return article;
    }

    async function postJson(url, payload = {}) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Falha na requisicao.");
      }
      return data;
    }

    function setBusy(isBusy) {
      promptInput.disabled = isBusy;
      sendBtn.disabled = isBusy;
      endBtn.disabled = isBusy;
      clearBtn.disabled = isBusy;
      statusText.textContent = isBusy ? "Lucios esta pensando..." : "Pronto para conversar";
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = promptInput.value.trim();
      if (!text) return;

      addMessage("user", "Voce", text);
      promptInput.value = "";
      setBusy(true);
      const typing = addTyping();

      try {
        const data = await postJson("/api/chat", { message: text });
        typing.remove();
        addMessage("assistant", "Lucios", data.reply);
      } catch (error) {
        typing.remove();
        addMessage("system", "Sistema", error.message);
      } finally {
        setBusy(false);
        promptInput.focus();
      }
    });

    promptInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    endBtn.addEventListener("click", async () => {
      setBusy(true);
      try {
        const data = await postJson("/api/end");
        addMessage("system", "Sistema", data.reply);
      } catch (error) {
        addMessage("system", "Sistema", error.message);
      } finally {
        setBusy(false);
        promptInput.focus();
      }
    });

    clearBtn.addEventListener("click", async () => {
      setBusy(true);
      try {
        await postJson("/api/clear");
        messages.innerHTML = "";
        addMessage("assistant", "Lucios", "Memoria limpa. Podemos recomecar.");
      } catch (error) {
        addMessage("system", "Sistema", error.message);
      } finally {
        setBusy(false);
        promptInput.focus();
      }
    });
  </script>
</body>
</html>
"""


class LuciosWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_html(HTML)
            return

        self.send_json({"error": "Rota nao encontrada."}, status=404)

    def do_POST(self):
        if self.path == "/api/chat":
            payload = self.read_json()
            message = str(payload.get("message", "")).strip()

            if not message:
                self.send_json({"error": "Mensagem vazia."}, status=400)
                return

            with agent_lock:
                reply = agent.chat(message)

            self.send_json({"reply": reply})
            return

        if self.path == "/api/clear":
            with agent_lock:
                reply = agent.clear_memory()

            self.send_json({"reply": reply})
            return

        if self.path == "/api/end":
            with agent_lock:
                reply = agent.end_conversation()

            self.send_json({"reply": reply})
            return

        self.send_json({"error": "Rota nao encontrada."}, status=404)

    def log_message(self, format, *args):
        return

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            return json.loads(raw_body)
        except JSONDecodeError:
            return {}

    def send_html(self, html, status=200):
        encoded = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run():
    server = ThreadingHTTPServer((HOST, PORT), LuciosWebHandler)
    print(f"Lucios web rodando em http://{HOST}:{PORT}")
    print("Pressione Ctrl+C para parar.")
    server.serve_forever()


if __name__ == "__main__":
    run()
