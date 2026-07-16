(() => {
  const $ = (id) => document.getElementById(id);
  const apiBase = "/api/v1";
  let sessionId = null;

  const apiKeyEl = $("apiKey");
  apiKeyEl.value = localStorage.getItem("rag_api_key") || "dev-admin-key";
  apiKeyEl.addEventListener("change", () => {
    localStorage.setItem("rag_api_key", apiKeyEl.value.trim());
  });

  function headers(json = true) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    const key = apiKeyEl.value.trim();
    if (key) h["X-API-Key"] = key;
    return h;
  }

  async function api(path, options = {}) {
    const res = await fetch(`${apiBase}${path}`, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail || data.message || res.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  async function refreshReady() {
    try {
      const r = await api("/ready");
      const ok = r.status === "ready";
      $("statusPill").className = ok ? "pill pill-ok" : "pill pill-warn";
      $("statusPill").textContent = ok ? "ready" : r.detail || "not ready";
    } catch {
      $("statusPill").className = "pill pill-err";
      $("statusPill").textContent = "offline";
    }
  }

  function renderSessions(items) {
    const el = $("sessionList");
    el.innerHTML = (items || [])
      .map(
        (s) =>
          `<button type="button" class="session-item ${
            s.id === sessionId ? "active" : ""
          }" data-id="${s.id}">${escapeHtml(s.title || "Chat")}</button>`
      )
      .join("");
    el.querySelectorAll(".session-item").forEach((btn) => {
      btn.addEventListener("click", () => openSession(btn.dataset.id));
    });
  }

  function renderMessages(messages) {
    const box = $("messages");
    if (!messages?.length) {
      box.innerHTML =
        '<div class="empty-hint">Ask a question grounded in uploaded company documents.</div>';
      return;
    }
    box.innerHTML = messages
      .map((m) => {
        const sources = (m.sources || [])
          .slice(0, 3)
          .map((s) => `<div>• ${escapeHtml((s.content || "").slice(0, 160))}</div>`)
          .join("");
        const meta =
          m.role === "assistant"
            ? `<div class="meta">lag=${escapeHtml(m.lag_stage || "—")} · cache=${escapeHtml(
                m.cache_hit || "none"
              )} · ${m.timings_ms?.total ?? "—"}ms</div>`
            : "";
        const src =
          sources && m.role === "assistant"
            ? `<div class="sources-mini"><strong>Sources</strong>${sources}</div>`
            : "";
        return `<div class="bubble ${m.role}">${escapeHtml(m.content)}${meta}${src}</div>`;
      })
      .join("");
    box.scrollTop = box.scrollHeight;
  }

  async function loadSessions() {
    const data = await api("/chat/sessions", { headers: headers(false) });
    renderSessions(data.items || []);
  }

  async function openSession(id) {
    sessionId = id;
    const data = await api(`/chat/sessions/${id}`, { headers: headers(false) });
    $("chatTitle").textContent = data.session?.title || "Chat";
    $("chatMeta").textContent = `namespace: ${data.session?.namespace || "default"}`;
    renderMessages(data.messages || []);
    await loadSessions();
  }

  $("btnNew").addEventListener("click", async () => {
    try {
      const data = await api("/chat/sessions", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ title: "New chat" }),
      });
      await openSession(data.session.id);
    } catch (e) {
      alert(e.message);
    }
  });

  $("composer").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = $("question").value.trim();
    if (!q) return;
    try {
      if (!sessionId) {
        const created = await api("/chat/sessions", {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({ title: q.slice(0, 60) }),
        });
        sessionId = created.session.id;
      }
      $("btnSend").disabled = true;
      $("question").value = "";
      const data = await api(`/chat/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ question: q }),
      });
      // reload full thread
      await openSession(sessionId);
      void data;
    } catch (e) {
      alert(e.message);
    } finally {
      $("btnSend").disabled = false;
    }
  });

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  refreshReady();
  loadSessions().catch(() => {});
})();
