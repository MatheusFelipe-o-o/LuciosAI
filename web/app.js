"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="lucios-token"]').content;
let currentId = null, recent = [], busy = true, labBusy = false, toastTimer;
let activeConversation = null, selectedModel = "auto", selectedEffort = "auto";
let thinkingInfo = null, editing = false, defaultModel = "Modelo local";
const thinkingCache = new Map();
const effortLevels = [
  ["light", "Light", "Leve e rápido, quando disponível"],
  ["medium", "Medium", "Equilíbrio, quando disponível"],
  ["high", "High", "Raciocínio ativado ou aprofundado"],
  ["extra_high", "Extra High", "Máximo nativo, quando disponível"]
];
let fileMode = false, pendingProposal = null, pendingSelection = null;
const promptInput = $("prompt"), messages = $("messages");

async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Lucios-Token": token},
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Não foi possível concluir a solicitação.");
  return data;
}
async function apiStream(path, payload, onEvent) {
  const response = await fetch(path, {
    method: "POST", headers: {"Content-Type": "application/json", "X-Lucios-Token": token},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || "Não foi possível iniciar a geração.");
  }
  if (!response.body) throw new Error("O navegador não recebeu o fluxo da resposta.");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let pending = "", finished = false;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      pending += decoder.decode(value, {stream: true});
      let newline;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        onEvent(event);
        if (event.type === "error") throw new Error(event.message || "Geração interrompida.");
        if (event.type === "done") finished = true;
      }
    }
    if (!finished) throw new Error("Conexão interrompida antes do fim da resposta.");
  } finally { reader.releaseLock(); }
}
function toast(text, url) {
  clearTimeout(toastTimer);
  $("toast").replaceChildren(document.createTextNode(text));
  if (url) {
    const link = document.createElement("a"); link.href = url; link.textContent = " Abrir Performance Lab ↗";
    link.target = "_blank"; link.rel = "noopener"; $("toast").append(link);
  }
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, url ? 20000 : 6500);
}
function setBusy(value) {
  busy = value;
  for (const id of ["sendBtn", "newBtn", "modelBtn", "effortBtn", "fileModeBtn"]) $(id).disabled = value;
  promptInput.disabled = value || editing || !!pendingProposal || !!pendingSelection;
  $("sendBtn").disabled = value || editing || !!pendingProposal || !!pendingSelection;
  $("endBtn").disabled = value || !currentId || !messages.children.length;
  messages.querySelectorAll?.("[data-turn-action]").forEach(button => {
    button.disabled = value || editing || button.dataset.boundary === "true";
  });
  messages.querySelectorAll?.(".edit-form button, .edit-form textarea").forEach(control => {
    control.disabled = value;
  });
  $("activity").classList.toggle("busy", value);
  $("status").textContent = value ? "Lucios está pensando…" : "Pronto para conversar";
}
function showWelcome(show) { $("welcome").hidden = !show; messages.hidden = show; }
function scrollChat() { $("chatArea").scrollTop = $("chatArea").scrollHeight; }
let followStream = true;
$("chatArea").addEventListener("scroll", () => {
  const area = $("chatArea");
  followStream = area.scrollHeight - area.scrollTop - area.clientHeight < 90;
});
function addMessage(role, text) {
  const article = document.createElement("article"); article.className = `message ${role}`;
  const header = document.createElement("div"); header.className = "message-header";
  const avatar = document.createElement("span"); avatar.className = "avatar"; avatar.textContent = role === "user" ? "V" : "L";
  const name = document.createElement("span"); name.textContent = role === "user" ? "Você" : "LuciosAI";
  header.append(avatar, name);
  const content = document.createElement("div"); content.className = "markdown-body";
  if (role === "assistant") renderMarkdown(text, content); else content.textContent = text;
  article.append(header, content); messages.append(article); return article;
}
function streamingMessage(existingArticle = null) {
  const article = existingArticle || addMessage("assistant", "");
  $("chatArea").classList.toggle("streaming", true);
  const content = article.children[1];
  let accumulated = "", timer = null;
  function paint() {
    timer = null;
    content.replaceChildren();
    renderMarkdown(accumulated, content);
    if (followStream) scrollChat();
  }
  return {
    article,
    append(part) {
      accumulated += part;
      if (timer === null) timer = setTimeout(paint, accumulated.length > 10000 ? 150 : 70);
    },
    finish() {
      if (timer !== null) clearTimeout(timer);
      paint();
      $("chatArea").classList.toggle("streaming", false);
    },
    get text() { return accumulated; }
  };
}
function failedStream(message, text, retryAction) {
  const note = document.createElement("div"); note.className = "stream-error";
  const label = document.createElement("span");
  label.textContent = "Geração interrompida: " + message;
  const retry = document.createElement("button");
  retry.type = "button"; retry.textContent = "Tentar novamente";
  retry.addEventListener("click", () => {
    if (busy) return;
    note.remove();
    if (retryAction) retryAction();
    else {
      const last = Array.from(messages.children).slice(-2);
      if (last[0]?.className === "message user" && last[1]?.className === "message assistant") {
        last.forEach(item => item.remove());
      }
      promptInput.value = text; resizeInput(); $("chatForm").requestSubmit();
    }
  });
  note.append(label, retry); messages.append(note); if (followStream) scrollChat();
}
function approvalCard(proposal, messageText) {
  pendingProposal = proposal;
  showWelcome(false);
  if (messageText) addMessage("user", messageText);
  const card = document.createElement("section"); card.className = "approval-card";
  card.setAttribute("aria-labelledby", "approval-title");
  const eyebrow = document.createElement("div"); eyebrow.className = "approval-eyebrow";
  eyebrow.textContent = "Aguardando sua decisão";
  const title = document.createElement("h2"); title.id = "approval-title"; title.tabIndex = -1;
  title.textContent = "Confirmar ação";
  const understood = document.createElement("p");
  const intro = document.createElement("strong"); intro.textContent = "Entendi seu pedido assim: ";
  understood.append(intro, document.createTextNode(proposal.interpretation));
  const details = document.createElement("div"); details.className = "approval-details";
  for (const [label, value] of [["Ação", proposal.operation], ["Pasta autorizada", proposal.root],
                                ["Origem", proposal.source], ["Destino", proposal.target],
                                ["Busca", proposal.query]]) {
    if (!value) continue;
    const row = document.createElement("div");
    const name = document.createElement("span"); name.textContent = label + ": ";
    row.append(name, document.createTextNode(value)); details.append(row);
  }
  const preview = document.createElement("pre"); preview.className = "approval-preview";
  preview.textContent = proposal.preview || "Sem prévia de conteúdo.";
  const actions = document.createElement("div"); actions.className = "approval-actions";
  const deny = document.createElement("button"); deny.type = "button"; deny.className = "approval-deny";
  deny.textContent = "Negar";
  const confirm = document.createElement("button"); confirm.type = "button"; confirm.className = "approval-confirm";
  confirm.textContent = "Confirmar";
  deny.addEventListener("click", () => decideFileAction(false));
  confirm.addEventListener("click", () => decideFileAction(true));
  actions.append(deny, confirm); card.append(eyebrow, title, understood, details, preview, actions);
  messages.append(card); scrollChat(); title.focus();
  setBusy(false);
}
function selectionCard(selection, messageText) {
  pendingSelection = selection;
  showWelcome(false);
  if (messageText) addMessage("user", messageText);
  const card = document.createElement("section"); card.className = "approval-card selection-card";
  card.setAttribute("aria-labelledby", "selection-title");
  const eyebrow = document.createElement("div"); eyebrow.className = "approval-eyebrow";
  eyebrow.textContent = "Preciso da sua escolha";
  const title = document.createElement("h2"); title.id = "selection-title"; title.tabIndex = -1;
  title.textContent = "Qual arquivo você quis dizer?";
  const explanation = document.createElement("p");
  explanation.textContent = selection.interpretation || `Encontrei ${selection.total} candidatos relacionados a “${selection.query}”.`;
  const hint = document.createElement("p"); hint.className = "selection-hint";
  hint.textContent = "Datas no nome e de modificação são pistas diferentes. Escolha o arquivo para continuar.";
  const list = document.createElement("div"); list.className = "selection-list";
  list.setAttribute("role", "group"); list.setAttribute("aria-label", "Arquivos candidatos");
  selection.candidates.forEach((candidate, index) => {
    const button = document.createElement("button"); button.type = "button";
    button.className = "selection-option";
    const name = document.createElement("strong"); name.textContent = candidate.path;
    const details = document.createElement("small");
    details.textContent = `${candidate.extension} · Alterado: ${candidate.modified}`
      + (candidate.name_date ? ` · Data no nome: ${candidate.name_date}` : "")
      + ` · ${candidate.reason}`;
    button.append(name, details);
    button.addEventListener("click", () => selectFileCandidate(index));
    list.append(button);
  });
  if (selection.total > selection.candidates.length) {
    const more = document.createElement("p"); more.className = "selection-hint";
    more.textContent = `Mostrando ${selection.candidates.length} de ${selection.total}. Refine o pedido se o arquivo não aparecer.`;
    list.append(more);
  }
  const cancel = document.createElement("button"); cancel.type = "button";
  cancel.className = "approval-deny selection-cancel"; cancel.textContent = "Cancelar";
  cancel.addEventListener("click", () => selectFileCandidate(null));
  card.append(eyebrow, title, explanation, hint, list, cancel);
  messages.append(card); scrollChat(); title.focus(); setBusy(false);
}
async function selectFileCandidate(index) {
  if (busy || !pendingSelection || !currentId) return;
  const selection = pendingSelection;
  setBusy(true);
  try {
    const data = await api("/api/files/select", {conversation_id: currentId,
      selection_id: selection.id, index});
    pendingSelection = null;
    if (data.cancelled) { renderConversation(); return; }
    Array.from(messages.children).find(node => node.className?.includes("selection-card"))?.remove();
    approvalCard(data.proposal);
  } catch (error) {
    pendingSelection = null; renderConversation(); toast(error.message);
  } finally { setBusy(false); renderRecent(); }
}
async function decideFileAction(confirm) {
  if (busy || !pendingProposal || !currentId) return;
  const proposal = pendingProposal;
  setBusy(true);
  try {
    const data = await api("/api/files/decide", {conversation_id: currentId,
      proposal_id: proposal.id, confirm});
    pendingProposal = null; pendingSelection = null;
    activeConversation = data.conversation;
    renderConversation();
    await refreshRecent();
    toast(data.result);
  } catch (error) {
    pendingProposal = null; messages.querySelector(".approval-card")?.remove();
    toast(error.message);
  } finally { setBusy(false); renderRecent(); promptInput.focus(); }
}
function turnButton(label, glyph, callback) {
  const button = document.createElement("button");
  button.type = "button"; button.className = "turn-action";
  button.textContent = glyph; button.title = label;
  button.setAttribute("aria-label", label);
  button.setAttribute("data-turn-action", "");
  button.disabled = busy;
  button.addEventListener("click", callback);
  return button;
}
function addTurnActions(article, item, i, entries) {
  if (!activeConversation?.editable || i < entries.length - 2) return;
  const actions = document.createElement("div"); actions.className = "message-actions";
  if (item.role === "user") {
    actions.append(turnButton("Editar este prompt", "✎", beginEdit));
  } else if (item.role === "assistant") {
    actions.append(turnButton("Tentar outra resposta", "↻", () => mutateTurn("/api/retry")));
    const alternatives = item.alternatives || [{content: item.content, model: null}];
    const chosen = item.selected || 0;
    if (alternatives.length > 1) {
      const prev = turnButton("Resposta anterior", "‹", () => mutateTurn("/api/select-answer", {index: chosen - 1}));
      prev.dataset.boundary = String(chosen === 0);
      prev.disabled = busy || chosen === 0;
      const count = document.createElement("span"); count.className = "answer-count";
      count.textContent = `${chosen + 1} de ${alternatives.length}`;
      const next = turnButton("Próxima resposta", "›", () => mutateTurn("/api/select-answer", {index: chosen + 1}));
      next.dataset.boundary = String(chosen === alternatives.length - 1);
      next.disabled = busy || chosen === alternatives.length - 1;
      actions.append(prev, count, next);
    }
    const model = alternatives[chosen]?.model;
    if (model) {
      const tag = document.createElement("span"); tag.className = "answer-model";
      tag.textContent = model; tag.title = `Resposta gerada por ${model}`; actions.append(tag);
    }
  }
  article.append(actions);
}
function renderConversation() {
  messages.replaceChildren();
  if (!activeConversation) return;
  const entries = activeConversation.messages;
  for (let i = 0; i < entries.length; i++) {
    const item = entries[i];
    const article = addMessage(item.role, item.content);
    addTurnActions(article, item, i, entries);
  }
  showWelcome(!entries.length);
  scrollChat();
}
async function mutateTurn(path, extra = {}) {
  if (busy || !activeConversation?.editable || (editing && path !== "/api/edit")) return false;
  const turn = activeConversation.editable_turn;
  const streamRevision = path === "/api/retry" || path === "/api/edit";
  const assistantArticle = Array.from(messages.children).filter(
    node => node.className === "message assistant").at(-1);
  let live = null;
  setBusy(true); renderRecent();
  try {
    if (streamRevision) {
      let completed = null;
      await apiStream("/api/turn-stream", {conversation_id: currentId, turn,
        action: path === "/api/edit" ? "edit" : "retry", ...extra}, event => {
        if (event.type === "delta") {
          if (!live) live = streamingMessage(assistantArticle);
          live.append(event.text);
        } else if (event.type === "state") {
          $("status").textContent = event.state === "thinking"
            ? "Raciocinando no modelo…" : "Gerando resposta…";
        } else if (event.type === "done") completed = event.conversation;
      });
      if (!live) {
        live = streamingMessage(assistantArticle);
        live.append(completed.messages.at(-1)?.content || "");
      }
      live.finish();
      activeConversation = completed;
      const entries = completed.messages, last = entries.length - 1;
      const userArticle = Array.from(messages.children).filter(
        node => node.className === "message user").at(-1);
      if (path === "/api/edit") userArticle.children[1].textContent = entries[last - 1].content;
      Array.from(userArticle.children).find(child => child.className === "message-actions")?.remove();
      Array.from(assistantArticle.children).find(child => child.className === "message-actions")?.remove();
      addTurnActions(userArticle, entries[last - 1], last - 1, entries);
      addTurnActions(assistantArticle, entries[last], last, entries);
    } else {
      const data = await api(path, {conversation_id: currentId, turn, ...extra});
      activeConversation = data.conversation;
      renderConversation();
    }
    editing = false;
    $("chatTitle").textContent = activeConversation.title;
    await refreshRecent().catch(() => toast("Resposta salva. Não foi possível atualizar Recentes."));
    return true;
  } catch (error) {
    if (live?.text) {
      live.finish(); failedStream(error.message, extra.message || activeConversation.messages.at(-2).content,
                                  () => mutateTurn(path, extra));
    } else toast(error.message);
    return false;
  }
  finally { setBusy(false); renderRecent(); }
}
function beginEdit() {
  if (busy || editing || !activeConversation?.editable) return;
  editing = true; setBusy(false);
  const article = messages.children[activeConversation.editable_turn];
  const content = article.children[1];
  const form = document.createElement("form"); form.className = "edit-form";
  const input = document.createElement("textarea"); input.value = activeConversation.messages.at(-2).content;
  input.maxLength = 16000; input.setAttribute("aria-label", "Editar prompt enviado");
  const buttons = document.createElement("div"); buttons.className = "edit-buttons";
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Cancelar";
  cancel.addEventListener("click", () => { editing = false; renderConversation(); setBusy(false); promptInput.focus(); });
  const save = document.createElement("button"); save.type = "submit"; save.textContent = "Salvar e gerar resposta";
  buttons.append(cancel, save); form.append(input, buttons); content.replaceChildren(form);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) { toast("Escreva um prompt antes de salvar."); return; }
    await mutateTurn("/api/edit", {message: text});
  });
  input.focus();
}
function typing() {
  const article = document.createElement("div"); article.className = "typing";
  article.setAttribute("aria-label", "Lucios está preparando uma resposta");
  for (let i=0;i<3;i++) article.append(document.createElement("i"));
  messages.append(article); scrollChat(); return article;
}
function dateGroup(value) {
  const day = new Date(value), now = new Date();
  if (day.toDateString() === now.toDateString()) return "Hoje";
  now.setDate(now.getDate()-1);
  if (day.toDateString() === now.toDateString()) return "Ontem";
  return "Anteriores";
}
function renderRecent() {
  const list = $("recentList"); list.replaceChildren();
  const query = $("search").value.trim().toLocaleLowerCase("pt-BR");
  const filtered = recent.filter(c => c.title.toLocaleLowerCase("pt-BR").includes(query));
  $("recentCount").textContent = recent.length;
  let group = "";
  for (const item of filtered) {
    const category = dateGroup(item.updated);
    if (category !== group) {
      const label = document.createElement("div"); label.className = "date-group";
      label.textContent = category; list.append(label); group = category;
    }
    const button = document.createElement("button"); button.className = "recent";
    button.textContent = item.title; button.title = item.title;
    button.setAttribute("aria-current", String(item.id === currentId));
    button.disabled = busy;
    button.addEventListener("click", () => openConversation(item.id));
    const row = document.createElement("div"); row.className = "recent-row";
    const remove = document.createElement("button"); remove.className = "delete-conversation";
    remove.title = "Excluir conversa"; remove.setAttribute("aria-label", `Excluir conversa: ${item.title}`);
    remove.disabled = busy;
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-trash"); icon.append(use); remove.append(icon);
    remove.addEventListener("click", () => deleteConversation(item));
    row.append(button, remove); list.append(row);
  }
  if (!filtered.length) {
    const empty = document.createElement("p"); empty.className = "list-empty";
    empty.textContent = query ? "Nenhuma conversa encontrada." : "Suas conversas aparecem aqui.";
    list.append(empty);
  }
}
async function deleteConversation(item) {
  if (busy || !window.confirm(`Excluir a conversa “${item.title}”?\n\nAs mensagens e o contexto deste chat serão removidos do histórico. Essa ação não pode ser desfeita. Resumos já salvos na memória serão mantidos.`)) return;
  setBusy(true); renderRecent(); $("status").textContent = "Excluindo conversa…";
  try {
    await api("/api/delete", {conversation_id: item.id});
    recent = recent.filter(c => c.id !== item.id);
    setBusy(false);
    if (currentId === item.id) newChat();
    renderRecent(); toast("Conversa excluída do histórico.");
  } catch (error) { toast(error.message); }
  finally { setBusy(false); renderRecent(); }
}
async function refreshRecent() {
  const data = await api("/api/conversations"); recent = data.conversations;
  defaultModel = data.model;
  updateModelLabel();
  const selected = recent.find(c => c.id === currentId);
  $("chatTitle").textContent = selected ? selected.title : "Nova conversa";
  renderRecent();
}
function updateModelLabel() {
  const label = selectedModel === "auto" ? "Automático" : selectedModel;
  $("modelName").textContent = label;
  $("modelBtn").title = selectedModel === "auto"
    ? `Seleção automática · padrão ${defaultModel}` : `Modelo selecionado: ${selectedModel}`;
  $("model").textContent = selectedModel === "auto" ? `Auto · ${defaultModel}` : selectedModel;
  $("model").title = $("modelBtn").title;
}
function updateEffortLabel() {
  const found = effortLevels.find(item => item[0] === selectedEffort);
  $("effortName").textContent = found ? found[1] : "Padrão";
  $("effortBtn").title = thinkingInfo?.mode === "none"
    ? "Este modelo não oferece controle de raciocínio"
    : `Esforço: ${found ? found[1] : "padrão do modelo"}`;
}
function renderEffortOptions() {
  const options = $("effortOptions"); options.replaceChildren();
  const mode = thinkingInfo?.mode || "none";
  $("effortInfo").textContent = mode === "named"
    ? "Níveis nativos informados pelo Ollama."
    : mode === "toggle"
      ? "Este modelo só permite desligar ou ativar o raciocínio. Não controla a profundidade."
      : "Este modelo não anuncia controle de raciocínio.";
  for (const [key, label, description] of effortLevels) {
    const enabled = !!thinkingInfo?.available?.[key];
    const button = document.createElement("button"); button.type = "button";
    button.className = "effort-option";
    button.disabled = !enabled || busy;
    button.setAttribute("aria-pressed", String(selectedEffort === key));
    const title = document.createElement("strong"); title.textContent = label;
    const detail = document.createElement("small");
    detail.textContent = enabled ? description : "Indisponível neste modelo";
    button.append(title, detail);
    button.addEventListener("click", () => chooseEffort(key));
    options.append(button);
  }
  $("effortAuto").disabled = busy;
  updateEffortLabel();
}
async function loadThinkingCapabilities() {
  const model = selectedModel;
  if (thinkingCache.has(model)) {
    thinkingInfo = thinkingCache.get(model); renderEffortOptions(); return;
  }
  try {
    const info = await api(`/api/thinking?model=${encodeURIComponent(model)}`);
    thinkingCache.set(model, info);
    if (selectedModel === model) { thinkingInfo = info; renderEffortOptions(); }
  } catch (error) {
    if (selectedModel === model) {
      thinkingInfo = null; renderEffortOptions();
      $("effortInfo").textContent = "Não foi possível consultar o Ollama local.";
    }
  }
}
async function chooseEffort(level) {
  if (busy || (level !== "auto" && !thinkingInfo?.available?.[level])) return;
  if (currentId) {
    try { await api("/api/effort", {conversation_id: currentId, effort: level}); }
    catch (error) { toast(error.message); return; }
  }
  selectedEffort = level;
  if (activeConversation) activeConversation.effort = level;
  renderEffortOptions();
  $("effortMenu").hidden = true;
  $("effortBtn").setAttribute("aria-expanded", "false");
}
$("effortBtn").addEventListener("click", async () => {
  if (busy) return;
  const opening = $("effortMenu").hidden;
  $("effortMenu").hidden = !opening;
  $("effortBtn").setAttribute("aria-expanded", String(opening));
  if (opening) await loadThinkingCapabilities();
});
$("effortAuto").addEventListener("click", () => chooseEffort("auto"));
function closeModelMenu() {
  $("modelMenu").hidden = true;
  $("modelBtn").setAttribute("aria-expanded", "false");
}
function modelOption(name, caption) {
  const button = document.createElement("button"); button.type = "button";
  button.className = "model-option"; button.textContent = name === "auto" ? "Automático" : name;
  button.setAttribute("aria-current", String(selectedModel === name));
  if (caption) {
    const hint = document.createElement("small"); hint.textContent = caption; button.append(hint);
  }
  button.addEventListener("click", async () => {
    if (busy) return;
    closeModelMenu();
    if (name === selectedModel) return;
    if (currentId) {
      setBusy(true); renderRecent();
      try { await api("/api/model", {conversation_id: currentId, model: name}); }
      catch (error) { toast(error.message); setBusy(false); renderRecent(); return; }
      finally { setBusy(false); renderRecent(); }
    }
    selectedModel = name;
    selectedEffort = "auto";
    if (activeConversation) activeConversation.model = name;
    if (activeConversation) activeConversation.effort = "auto";
    updateModelLabel();
    thinkingInfo = null; updateEffortLabel(); loadThinkingCapabilities();
  });
  return button;
}
$("modelBtn").addEventListener("click", async () => {
  if (busy) return;
  if (!$("modelMenu").hidden) { closeModelMenu(); return; }
  $("modelMenu").hidden = false;
  $("modelBtn").setAttribute("aria-expanded", "true");
  $("modelOptions").replaceChildren(modelOption("auto", "Escolha do orquestrador"));
  try {
    const data = await api("/api/models");
    if (!data.available) throw new Error("Ollama local indisponível. O modo Automático continua disponível.");
    for (const name of data.models) $("modelOptions").append(modelOption(name));
    if (!data.models.length) {
      const empty = document.createElement("div"); empty.className = "model-unavailable";
      empty.textContent = "Nenhum modelo instalado."; $("modelOptions").append(empty);
    }
  } catch (error) { toast(error.message); }
});
function sidebar(open) {
  const mobile = window.matchMedia("(max-width: 760px)").matches;
  document.body.classList.toggle("mobile-open", mobile && open);
  if (!mobile) document.body.classList.toggle("sidebar-closed", !open);
  $("scrim").hidden = !(mobile && open);
  $("sidebar").inert = !open;
  $("workspace").inert = mobile && open;
  $("menuBtn").setAttribute("aria-expanded", String(open));
  $("closeSidebar").setAttribute("aria-expanded", String(open));
}
async function openConversation(id) {
  if (busy) return;
  closeModelMenu();
  setBusy(true); renderRecent();
  try {
    const data = await api(`/api/conversation?id=${encodeURIComponent(id)}`);
    currentId = data.id; activeConversation = data;
    selectedModel = data.model || "auto"; selectedEffort = data.effort || "auto";
    updateModelLabel(); loadThinkingCapabilities();
    editing = false; renderConversation();
    pendingProposal = null; pendingSelection = null;
    const pending = await api(`/api/files/pending?conversation_id=${encodeURIComponent(id)}`);
    if (pending.proposal) approvalCard(pending.proposal, pending.proposal.request);
    else if (pending.selection) selectionCard(pending.selection, pending.selection.request);
    $("chatTitle").textContent = data.title;
    promptInput.value = ""; resizeInput();
    if (window.matchMedia("(max-width: 760px)").matches) sidebar(false);
    scrollChat();
  } catch (error) { toast(error.message); }
  finally { setBusy(false); renderRecent(); promptInput.focus(); }
}
function newChat() {
  if (busy) return;
  currentId = null; activeConversation = null; editing = false; pendingProposal = null; pendingSelection = null;
  selectedModel = "auto"; selectedEffort = "auto";
  updateModelLabel(); updateEffortLabel(); closeModelMenu();
  messages.replaceChildren(); showWelcome(true);
  $("chatTitle").textContent = "Nova conversa"; promptInput.value = ""; resizeInput();
  setBusy(false); renderRecent();
  if (window.matchMedia("(max-width: 760px)").matches) sidebar(false);
  promptInput.focus();
}
function resizeInput() { promptInput.style.height = "auto"; promptInput.style.height = `${Math.min(170, promptInput.scrollHeight)}px`; }
$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault(); if (busy || pendingProposal || pendingSelection) return;
  const text = promptInput.value.trim(); if (!text) return;
  const area = $("chatArea");
  const distance = area.scrollHeight - area.scrollTop - area.clientHeight;
  followStream = !Number.isFinite(distance) || distance < 90;
  setBusy(true); renderRecent(); showWelcome(false);
  const userMessage = addMessage("user", text); const pending = typing();
  let partial = null;
  promptInput.value = ""; resizeInput();
  try {
    if (!currentId) currentId = (await api("/api/new", {
      model: selectedModel, effort: selectedEffort})).id;
    if (!fileMode) {
      let completed = null;
      await apiStream("/api/chat-stream", {message: text, conversation_id: currentId}, event => {
        if (event.type === "delta") {
          if (!partial) { pending.remove(); partial = streamingMessage(); }
          partial.append(event.text);
        } else if (event.type === "state") {
          $("status").textContent = event.state === "thinking"
            ? "Raciocinando no modelo…" : "Gerando resposta…";
        } else if (event.type === "done") completed = event.conversation;
      });
      pending.remove();
      if (!partial) {
        partial = streamingMessage();
        partial.append(completed.messages.at(-1)?.content || "");
      }
      partial.finish();
      activeConversation = completed;
      const entries = completed.messages, last = entries.length - 1;
      for (const article of Array.from(messages.children).slice(0, -2)) {
        Array.from(article.children).find(child => child.className === "message-actions")?.remove();
      }
      addTurnActions(userMessage, entries[last - 1], last - 1, entries);
      addTurnActions(partial.article, entries[last], last, entries);
      await refreshRecent().catch(() => toast("Resposta salva. Não foi possível atualizar Recentes."));
      return;
    }
    const data = await api("/api/files/prepare", {message: text, conversation_id: currentId});
    pending.remove();
    if (data.selection) {
      userMessage.remove();
      selectionCard(data.selection, text);
    } else if (data.proposal) {
      userMessage.remove();
      approvalCard(data.proposal, text);
    } else if (data.clarification) {
      addMessage("assistant", data.clarification); scrollChat();
    } else if (data.conversation) {
      activeConversation = data.conversation;
      renderConversation();
    } else {
      addMessage("assistant", data.reply); scrollChat();
    }
    await refreshRecent().catch(() => toast("Resposta salva. Não foi possível atualizar a lista de recentes."));
  } catch (error) {
    pending.remove();
    if (partial?.text) {
      partial.finish(); failedStream(error.message, text);
    } else {
      partial?.article.remove(); userMessage.remove(); promptInput.value = text; resizeInput();
      showWelcome(!messages.children.length); toast(error.message);
    }
  } finally { setBusy(false); renderRecent(); if (!pendingProposal) promptInput.focus(); }
});
$("fileModeBtn").addEventListener("click", () => {
  if (busy || pendingProposal) return;
  fileMode = !fileMode;
  $("fileModeBtn").setAttribute("aria-pressed", String(fileMode));
  $("composerMode").textContent = fileMode ? "/ Arquivos" : "/ Conversa";
  promptInput.placeholder = fileMode ? "Descreva a ação em arquivos…" : "O que vamos construir hoje?";
  promptInput.focus();
});
promptInput.addEventListener("input", resizeInput);
promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); if (!busy) $("chatForm").requestSubmit();
  }
});
$("newBtn").addEventListener("click", newChat);
$("chatNav").addEventListener("click", () => { if (window.matchMedia("(max-width: 760px)").matches) sidebar(false); promptInput.focus(); });
$("search").addEventListener("input", renderRecent);
$("menuBtn").addEventListener("click", () => sidebar(true));
$("closeSidebar").addEventListener("click", () => { sidebar(false); $("menuBtn").focus(); });
$("scrim").addEventListener("click", () => { sidebar(false); $("menuBtn").focus(); });
document.addEventListener("keydown", (event) => {
  if (event.altKey && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); }
  if (event.key === "Escape") {
    if (!$("modelMenu").hidden) { closeModelMenu(); $("modelBtn").focus(); }
    else if (!$("effortMenu").hidden) {
      $("effortMenu").hidden = true; $("effortBtn").setAttribute("aria-expanded", "false");
      $("effortBtn").focus();
    }
    else { sidebar(false); $("menuBtn").focus(); }
  }
});
window.matchMedia("(max-width: 760px)").addEventListener("change", event => sidebar(!event.matches));
document.querySelectorAll("[data-prompt]").forEach(button => button.addEventListener("click", () => {
  if (!busy) { promptInput.value = button.dataset.prompt; resizeInput(); promptInput.focus(); }
}));
$("endBtn").addEventListener("click", async () => {
  if (busy || !currentId) return;
  setBusy(true); renderRecent();
  try {
    await api("/api/end", {conversation_id: currentId});
    toast("Resumo salvo na memória. A conversa completa continua em Recentes.");
    setBusy(false); newChat();
    await refreshRecent();
  } catch (error) { toast(error.message); }
  finally { setBusy(false); renderRecent(); }
});
async function openLab() {
  if (labBusy) return;
  const target = window.open("about:blank", "_blank");
  if (target) target.opener = null;
  labBusy = true; $("labBtn").disabled = true; $("labCard").disabled = true;
  try {
    const data = await api("/api/lab", {});
    if (target) target.location.replace(data.url);
    else toast("O laboratório está pronto.", data.url);
  } catch (error) { if (target) target.close(); toast(error.message); }
  finally { labBusy = false; $("labBtn").disabled = false; $("labCard").disabled = false; }
}
$("labBtn").addEventListener("click", openLab);
$("labCard").addEventListener("click", openLab);
setBusy(true); $("status").textContent = "Carregando seu espaço…";
sidebar(!window.matchMedia("(max-width: 760px)").matches);
refreshRecent().catch(error => toast(error.message)).finally(() => {
  setBusy(false); renderRecent(); loadThinkingCapabilities(); promptInput.focus();
});
