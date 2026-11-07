"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const storeKey = "ampere-support-tab-v1";
  const fresh = () => ({ conversationId: crypto.randomUUID(), messages: [], pending: null });
  let state;
  try {
    const saved = JSON.parse(sessionStorage.getItem(storeKey));
    const validMessages = saved && Array.isArray(saved.messages) && saved.messages.length <= 200
      && saved.messages.every((message) => message && ["user", "assistant"].includes(message.role) && typeof message.text === "string");
    const validPending = saved && (!saved.pending || (saved.pending.conversation_id === saved.conversationId
      && /^[A-Za-z0-9_-]{1,128}$/.test(saved.pending.request_id)
      && typeof saved.pending.message === "string" && saved.pending.message.length <= 4000));
    state = saved && /^[A-Za-z0-9_-]{1,128}$/.test(saved.conversationId)
      && validMessages && validPending ? saved : fresh();
  } catch { state = fresh(); }
  let busy = false;
  const save = () => { try { sessionStorage.setItem(storeKey, JSON.stringify({ ...state, messages: state.messages.slice(-200) })); } catch { /* Chat still works without storage. */ } };
  const scroll = () => { $("conversation-scroll").scrollTop = $("conversation-scroll").scrollHeight; };
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const outcomes = { answered: "Answered", needs_clarification: "A quick follow-up", escalated: "Mock handoff complete", escalation_pending: "Handoff pending" };

  function assistantText(text) {
    // A tiny safe formatting subset; never parse HTML or turn model text into links.
    const container = element("div", "message-text");
    const normalized = text.replace(/^#{1,6}\s+/gm, "").replace(/^```[^\n]*\n?|^```\s*$/gm, "");
    for (const part of normalized.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
      if (part.startsWith("**") && part.endsWith("**")) container.append(element("strong", "", part.slice(2, -2)));
      else if (part.startsWith("`") && part.endsWith("`")) container.append(element("code", "", part.slice(1, -1)));
      else container.append(document.createTextNode(part));
    }
    return container;
  }

  function appendMessage(message) {
    const user = message.role === "user";
    const row = element("div", `message-row ${user ? "user" : "assistant"}`);
    const avatar = element("span", "mini-avatar", user ? "YOU" : "ϟ");
    avatar.setAttribute("aria-hidden", "true");
    const content = element("div", "message-content");
    const meta = element("div", "message-meta", user ? "You" : "Ampere assistant");
    if (!user && outcomes[message.outcome]) meta.append(element("span", `outcome ${message.outcome}`, outcomes[message.outcome]));
    content.append(meta, user ? element("div", "message-text", message.text) : assistantText(message.text));
    if (!user && Array.isArray(message.sources) && message.sources.length) {
      const sources = element("div", "sources");
      for (const source of message.sources) {
        try {
          const url = new URL(source.url);
          if (url.protocol !== "https:" || url.hostname !== "docs.ampere.sh" || url.username || url.password
            || !(url.pathname === "/docs" || url.pathname.startsWith("/docs/"))) continue;
          const link = element("a", "", `↗ ${source.title || "Ampere documentation"}`);
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          sources.append(link);
        } catch { /* Untrusted URLs never become links. */ }
      }
      if (sources.childElementCount) content.append(sources);
    }
    if (!user && typeof message.ticket_id === "string" && message.ticket_id) {
      const pending = message.outcome === "escalation_pending";
      const ticket = element("div", `ticket${pending ? " pending" : ""}`);
      ticket.append(element("strong", "", pending ? "Ticket saved · delivery pending" : "Your support ticket"),
        element("span", "", `Ticket ${message.ticket_id}`));
      content.append(ticket);
    }
    row.append(avatar, content);
    $("messages").append(row);
  }

  function updateControls() {
    $("send").disabled = busy || Boolean(state.pending) || !$("message").value.trim();
    $("message").disabled = busy || Boolean(state.pending);
    $("new-chat").disabled = busy;
    document.querySelectorAll("[data-prompt], [data-email]").forEach((button) => { button.disabled = busy || Boolean(state.pending); });
    $("thinking").hidden = !busy;
    $("message").style.height = "auto";
    $("message").style.height = `${Math.min($("message").scrollHeight, 130)}px`;
    $("character-count").textContent = `${$("message").value.length}/4000`;
    $("character-count").hidden = $("message").value.length < 3200;
    $("welcome").hidden = state.messages.length > 0;
    $("messages").setAttribute("aria-busy", String(busy));
  }

  function showError(text) {
    $("error-text").textContent = text;
    $("error-notice").hidden = false;
  }

  async function deliver() {
    if (busy || !state.pending) return;
    busy = true;
    $("error-notice").hidden = true;
    updateControls();
    scroll();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 75000);
    try {
      const response = await fetch("/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.pending), signal: controller.signal,
      });
      if (!response.ok) {
        const error = new Error(response.status === 503 ? "The assistant is temporarily unavailable. Try this message again."
          : response.status === 409 ? "This message could not be resumed. Start a new chat to continue."
          : response.status === 422 || response.status === 413 ? "This message could not be accepted. Start a new chat and send a shorter message."
          : "We couldn’t get a reply. Try this message again.");
        throw error;
      }
      const data = await response.json();
      if (data.conversation_id !== state.conversationId || typeof data.answer !== "string" || !outcomes[data.outcome]) {
        throw new Error("We received an incomplete reply. Try this message again.");
      }
      const message = { role: "assistant", text: data.answer, sources: data.sources,
        outcome: data.outcome, ticket_id: data.ticket_id };
      state.messages.push(message);
      state.pending = null;
      appendMessage(message);
      save();
    } catch (error) {
      showError(error.name === "AbortError" ? "The reply took too long. Try again—we’ll reuse the same message to avoid duplicates."
        : error instanceof TypeError ? "Couldn’t reach the server. Check that it’s running, then try again." : error.message);
    } finally {
      clearTimeout(timer);
      busy = false;
      updateControls();
      if (!state.pending) $("message").focus({ preventScroll: true });
      scroll();
    }
  }

  function send(text) {
    if (busy || state.pending || !text.trim() || text.length > 4000) return;
    const message = { role: "user", text: text.trim() };
    state.pending = { conversation_id: state.conversationId, request_id: crypto.randomUUID(), message: message.text };
    state.messages.push(message);
    $("message").value = "";
    appendMessage(message);
    save();
    deliver();
  }

  $("chat-form").addEventListener("submit", (event) => { event.preventDefault(); send($("message").value); });
  $("message").addEventListener("input", updateControls);
  $("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); send($("message").value);
    }
  });
  $("retry").addEventListener("click", deliver);
  $("new-chat").addEventListener("click", () => {
    if (busy) return;
    state = fresh();
    save();
    $("messages").replaceChildren();
    $("message").value = "";
    $("error-notice").hidden = true;
    updateControls();
    $("message").focus();
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => send(button.dataset.prompt)));
  document.querySelectorAll("[data-email]").forEach((button) => button.addEventListener("click", () => {
    if (busy || state.pending) return;
    $("message").value = button.dataset.email;
    updateControls();
    $("message").focus();
  }));
  for (const message of state.messages) appendMessage(message);
  if (state.pending) showError("Your last message hasn’t been confirmed. Try again to resume it, or start a new chat.");
  updateControls();
  scroll();
  fetch("/health").then((response) => {
    if (!response.ok) throw new Error();
    $("connection").textContent = "Ready to help";
  }).catch(() => {
    $("connection").textContent = "Server unavailable";
    $("connection-dot").classList.add("off");
  });
})();
