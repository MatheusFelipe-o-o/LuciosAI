"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="lucios-token"]').content;
let currentId = null, recent = [], busy = true, labBusy = false, toastTimer;
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
  for (const id of ["sendBtn", "newBtn"]) $(id).disabled = value;
  promptInput.disabled = value;
  $("endBtn").disabled = value || !currentId || !messages.children.length;
  $("activity").classList.toggle("busy", value);
  $("status").textContent = value ? "Lucios está pensando…" : "Pronto para conversar";
}
function showWelcome(show) { $("welcome").hidden = !show; messages.hidden = show; }
function scrollChat() { $("chatArea").scrollTop = $("chatArea").scrollHeight; }
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
  $("model").textContent = data.model; $("model").title = data.model;
  const selected = recent.find(c => c.id === currentId);
  $("chatTitle").textContent = selected ? selected.title : "Nova conversa";
  renderRecent();
}
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
  setBusy(true); renderRecent();
  try {
    const data = await api(`/api/conversation?id=${encodeURIComponent(id)}`);
    currentId = data.id; messages.replaceChildren();
    for (const item of data.messages) addMessage(item.role, item.content);
    $("chatTitle").textContent = data.title; showWelcome(!data.messages.length);
    promptInput.value = ""; resizeInput();
    if (window.matchMedia("(max-width: 760px)").matches) sidebar(false);
    scrollChat();
  } catch (error) { toast(error.message); }
  finally { setBusy(false); renderRecent(); promptInput.focus(); }
}
function newChat() {
  if (busy) return;
  currentId = null; messages.replaceChildren(); showWelcome(true);
  $("chatTitle").textContent = "Nova conversa"; promptInput.value = ""; resizeInput();
  setBusy(false); renderRecent();
  if (window.matchMedia("(max-width: 760px)").matches) sidebar(false);
  promptInput.focus();
}
function resizeInput() { promptInput.style.height = "auto"; promptInput.style.height = `${Math.min(170, promptInput.scrollHeight)}px`; }
$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault(); if (busy) return;
  const text = promptInput.value.trim(); if (!text) return;
  setBusy(true); renderRecent(); showWelcome(false);
  const userMessage = addMessage("user", text); const pending = typing();
  promptInput.value = ""; resizeInput();
  try {
    if (!currentId) currentId = (await api("/api/new", {})).id;
    const data = await api("/api/chat", {message: text, conversation_id: currentId});
    pending.remove(); addMessage("assistant", data.reply); scrollChat();
    await refreshRecent().catch(() => toast("Resposta salva. Não foi possível atualizar a lista de recentes."));
  } catch (error) {
    pending.remove(); userMessage.remove(); promptInput.value = text; resizeInput();
    showWelcome(!messages.children.length); toast(error.message);
  } finally { setBusy(false); renderRecent(); promptInput.focus(); }
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
  if (event.key === "Escape") { sidebar(false); $("menuBtn").focus(); }
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
refreshRecent().catch(error => toast(error.message)).finally(() => { setBusy(false); renderRecent(); promptInput.focus(); });
