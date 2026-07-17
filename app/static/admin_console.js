(() => {
  const $ = (id) => document.getElementById(id);
  const api = "/api/v1";
  const STORAGE_KEY = "rag_admin_key";

  const titles = {
    home: ["Home", "Setup checklist — live from Postgres"],
    companies: ["Companies", "Client companies · keys, docs, per-company RAG config"],
    test: ["Test API", "Chat with a real tenant API key"],
    system: ["System", "Integrations and platform defaults"],
  };

  const state = {
    adminKey: "",
    connected: false,
    tenants: [],
    setup: null,
    config: null,
    selectedId: null,
    desk: null,
    deskTab: "overview",
    busy: 0,
    testKeys: JSON.parse(sessionStorage.getItem("rag_test_keys") || "{}"),
    testMessages: [],
  };

  // ── helpers ──
  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function cleanKey(v) {
    let s = String(v ?? "").trim();
    if (
      s.length >= 2 &&
      ((s[0] === '"' && s[s.length - 1] === '"') ||
        (s[0] === "'" && s[s.length - 1] === "'"))
    ) {
      s = s.slice(1, -1).trim();
    }
    return s;
  }

  function formatError(detail, statusText) {
    if (detail == null || detail === "") return statusText || "Request failed";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((x) => (typeof x === "string" ? x : x.msg || JSON.stringify(x))).join("; ");
    }
    if (typeof detail === "object") return detail.message || JSON.stringify(detail);
    return String(detail);
  }

  function headers(json = true) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    const k = cleanKey(state.adminKey);
    if (k) h["X-API-Key"] = k;
    return h;
  }

  function setGlobalLoading(on) {
    $("globalLoad").classList.toggle("on", !!on);
  }

  function pushBusy(delta) {
    state.busy = Math.max(0, state.busy + delta);
    setGlobalLoading(state.busy > 0);
  }

  function setBtnLoading(btn, loading, label) {
    if (!btn) return;
    const span = btn.querySelector(".btn-label") || btn;
    if (loading) {
      btn.disabled = true;
      btn.dataset.prev = span.textContent || "";
      span.innerHTML = `<span class="spin"></span> ${esc(label || "Working…")}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.prev != null) span.textContent = btn.dataset.prev;
    }
  }

  async function req(path, opts = {}) {
    pushBusy(1);
    try {
      const r = await fetch(api + path, opts);
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatError(d.detail || d.message, r.statusText));
      return d;
    } finally {
      pushBusy(-1);
    }
  }

  function flash(msg, ok = true) {
    const strip = $("toastStrip");
    const el = document.createElement("div");
    el.className = "toast-item " + (ok ? "ok" : "err");
    el.textContent = msg;
    strip.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  let dlgResolve = null;
  function closeDialog(result) {
    $("modalDialog").classList.add("hidden");
    const r = dlgResolve;
    dlgResolve = null;
    if (r) r(result);
  }

  function showDialog(opts) {
    const ok = opts.ok !== false;
    const kind = opts.kind || (ok ? "ok" : "err");
    $("dlgIcon").className = "dlg-icon " + kind;
    $("dlgIcon").textContent = kind === "ok" ? "✓" : kind === "warn" ? "!" : "!";
    $("dlgTitle").textContent = opts.title || (ok ? "Success" : "Error");
    $("dlgMessage").textContent = opts.message || "";
    const sec = $("dlgSecret");
    if (opts.secret) {
      sec.classList.remove("hidden");
      sec.innerHTML = `<strong>Copy now (shown once)</strong><br/>${esc(opts.secret)}
        <br/><button type="button" class="btn sm" style="margin-top:8px" id="dlgCopy">Copy</button>`;
      const btn = $("dlgCopy");
      if (btn) {
        btn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(opts.secret);
            btn.textContent = "Copied";
            flash("Copied to clipboard");
          } catch {
            btn.textContent = "Select text manually";
          }
        };
      }
    } else {
      sec.classList.add("hidden");
      sec.innerHTML = "";
    }
    const actions = $("dlgActions");
    if (opts.confirm) {
      actions.innerHTML = `
        <button type="button" class="btn" id="dlgCancel">${esc(opts.cancelLabel || "Cancel")}</button>
        <button type="button" class="btn ${ok ? "primary" : "danger"}" id="dlgOk">${esc(
          opts.confirmLabel || "Confirm"
        )}</button>`;
      $("dlgCancel").onclick = () => closeDialog(false);
      $("dlgOk").onclick = () => closeDialog(true);
    } else {
      actions.innerHTML = `<button type="button" class="btn primary" id="dlgOk">${esc(
        opts.confirmLabel || "OK"
      )}</button>`;
      $("dlgOk").onclick = () => closeDialog(true);
    }
    $("modalDialog").classList.remove("hidden");
    return new Promise((resolve) => {
      dlgResolve = resolve;
    });
  }

  const notifySuccess = (title, message, secret) =>
    showDialog({ title, message, ok: true, secret });
  const notifyError = (title, message) =>
    showDialog({ title: title || "Error", message: message || "Something went wrong", ok: false });
  const confirmAction = (title, message, confirmLabel) =>
    showDialog({
      title,
      message,
      ok: false,
      kind: "warn",
      confirm: true,
      confirmLabel: confirmLabel || "Confirm",
    });

  async function copyText(label, value) {
    try {
      await navigator.clipboard.writeText(value);
      flash(`Copied ${label}`);
    } catch {
      await notifyError("Copy failed", "Select the text and copy manually.");
    }
  }

  function baseUrl() {
    const fromEnv = (state.config?.public_base_url || state.setup?.public_base_url || "").trim();
    return (fromEnv || window.location.origin).replace(/\/$/, "");
  }
  function apiPrefix() {
    return state.config?.api_prefix || state.setup?.api_prefix || "/api/v1";
  }

  // ── Auth ──
  function setConnectedUI(connected) {
    state.connected = connected;
    $("authGate").classList.toggle("hidden", connected);
    $("appShell").classList.toggle("hidden", !connected);
    if (connected) {
      const k = state.adminKey;
      $("authKeyHint").textContent = k ? `${k.slice(0, 6)}…${k.slice(-4)}` : "(auth off)";
    }
  }

  function showGateError(msg) {
    const el = $("gateError");
    if (!msg) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  function validateKeyInput(raw) {
    const k = cleanKey(raw);
    if (!k) return { ok: false, error: "Admin key is required." };
    if (k.length < 4) return { ok: false, error: "Key looks too short." };
    if (/\s/.test(k)) return { ok: false, error: "Key must not contain spaces." };
    return { ok: true, key: k };
  }

  async function connectWithKey(raw, { silent = false } = {}) {
    const v = validateKeyInput(raw);
    let key = v.ok ? v.key : cleanKey(raw);
    if (!v.ok && key) {
      showGateError(v.error);
      if (!silent) await notifyError("Invalid key", v.error);
      return false;
    }
    state.adminKey = key;
    const btn = $("gateConnect");
    if (!silent) setBtnLoading(btn, true, "Connecting…");
    try {
      const me = await req("/admin/auth/verify", { headers: headers(false) });
      localStorage.setItem(STORAGE_KEY, key);
      setConnectedUI(true);
      showGateError("");
      await refresh();
      if (!silent) {
        await notifySuccess(
          "Connected",
          me.auth_enabled === false
            ? "Auth is disabled on the server. Full admin access granted."
            : `Admin key accepted (${me.key_name || "admin"}).`
        );
      }
      return true;
    } catch (e) {
      state.connected = false;
      localStorage.removeItem(STORAGE_KEY);
      showGateError(e.message);
      setConnectedUI(false);
      if (!silent) await notifyError("Authentication failed", e.message);
      return false;
    } finally {
      if (!silent) setBtnLoading(btn, false);
    }
  }

  $("gateToggle").onclick = () => {
    const inp = $("gateKey");
    const show = inp.type === "password";
    inp.type = show ? "text" : "password";
    $("gateToggle").textContent = show ? "Hide" : "Show";
  };
  $("gateConnect").onclick = () => connectWithKey($("gateKey").value);
  $("gateKey").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      $("gateConnect").click();
    }
  });
  $("btnDisconnect").onclick = () => {
    state.adminKey = "";
    state.connected = false;
    localStorage.removeItem(STORAGE_KEY);
    $("gateKey").value = "";
    setConnectedUI(false);
  };

  // ── nav ──
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      const v = btn.dataset.view;
      $("view-" + v).classList.add("active");
      const [t, s] = titles[v] || [v, ""];
      $("pageTitle").textContent = t;
      $("pageSub").textContent = s;
      if (v === "test") renderTestCompanySelect();
    };
  });

  // ── load ──
  async function refresh() {
    if (!state.connected && !state.adminKey) return;
    try {
      const [dash, conf, tenants] = await Promise.all([
        req("/admin/dashboard", { headers: headers(false) }),
        req("/admin/system/config", { headers: headers(false) }),
        req("/admin/tenants", { headers: headers(false) }),
      ]);
      state.setup = dash.setup;
      state.config = conf;
      state.tenants = tenants.items || [];
      renderHome();
      renderCompanies();
      renderSystem();
      renderTestCompanySelect();
      if (state.selectedId && !$("desk").classList.contains("hidden")) {
        await openDesk(state.selectedId, false);
      }
      const integ = state.setup?.integrations || {};
      const ok = integ.database && integ.openrouter && integ.pinecone;
      $("statusPill").className = "pill " + (ok ? "ok" : "warn");
      $("statusPill").textContent = ok ? "core ready" : "setup needed";
    } catch (e) {
      $("statusPill").className = "pill err";
      $("statusPill").textContent = "error";
      if (/invalid api key|missing api key|missing scopes|unauthorized|forbidden/i.test(e.message)) {
        setConnectedUI(false);
        showGateError(e.message);
        await notifyError("Session expired", e.message);
      } else {
        $("nextBox").textContent = "Cannot load dashboard: " + e.message;
        flash(e.message, false);
      }
    }
  }

  function renderHome() {
    const setup = state.setup || {};
    const prog = setup.progress || { done: 0, total: 7 };
    const counts = setup.counts || {};
    $("progressText").textContent = `${prog.done} / ${prog.total}`;
    $("progressFill").style.width = `${(100 * prog.done) / (prog.total || 1)}%`;
    const next = setup.next_step;
    const nb = $("nextBox");
    if (setup.setup_complete) {
      nb.className = "next-box done";
      nb.innerHTML =
        "<strong>Setup complete.</strong> Use Companies → Configure for RAG settings.";
    } else if (next) {
      nb.className = "next-box";
      nb.innerHTML = `<strong>Next:</strong> ${esc(next.title)}<br/>${esc(next.hint)}`;
    }
    $("howList").innerHTML = (setup.how_it_works || []).map((x) => `<li>${esc(x)}</li>`).join("");
    $("statGrid").innerHTML = [
      ["Companies", counts.active_tenants ?? 0],
      ["Active keys", counts.tenant_keys_active ?? 0],
      ["Docs ready", counts.documents_ready ?? 0],
      ["Queries", counts.queries ?? 0],
      ["All docs", counts.documents ?? 0],
    ]
      .map(
        ([l, v]) =>
          `<div class="stat"><div class="lbl">${esc(l)}</div><div class="val">${esc(v)}</div></div>`
      )
      .join("");
    $("checklist").innerHTML = (setup.steps || [])
      .map(
        (s) => `<div class="check-item ${s.done ? "done" : ""}">
        <div class="check-dot">${s.done ? "✓" : "·"}</div>
        <div><div class="check-title">${esc(s.title)}</div>
        <div class="check-hint">${esc(s.hint)}</div></div></div>`
      )
      .join("");
  }

  function renderCompanies() {
    const q = ($("companySearch").value || "").toLowerCase();
    const list = state.tenants.filter(
      (t) =>
        !q ||
        (t.name || "").toLowerCase().includes(q) ||
        (t.slug || "").toLowerCase().includes(q)
    );
    $("companiesEmpty").classList.toggle("hidden", list.length > 0);
    $("companyGrid").innerHTML = list
      .map(
        (t) => `<article class="company-card">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:start">
          <h4>${esc(t.name)}</h4>
          <span class="badge ${t.status === "active" ? "ok" : "err"}">${esc(t.status)}</span>
        </div>
        <div class="company-meta">
          Namespace: <span class="mono">${esc(t.pinecone_namespace)}</span><br/>
          Model: ${esc(t.default_model || "—")}<br/>
          top_k: ${t.top_k ?? "default"} · return: ${t.return_top_n ?? "default"}<br/>
          Keys: ${t.keys_active ?? 0} · Docs: ${t.documents_ready ?? 0}/${t.documents ?? 0} · Q: ${t.query_count ?? 0}
        </div>
        <div class="company-actions">
          <button type="button" class="btn primary sm" data-cfg="${t.id}">Configure</button>
          <button type="button" class="btn sm" data-test="${t.id}">Test API</button>
        </div>
      </article>`
      )
      .join("");
    $("companyGrid").querySelectorAll("[data-cfg]").forEach((b) => {
      b.onclick = () => openDesk(b.dataset.cfg);
    });
    $("companyGrid").querySelectorAll("[data-test]").forEach((b) => {
      b.onclick = () => {
        document.querySelector('.nav-item[data-view="test"]').click();
        $("testCompany").value = b.dataset.cfg;
        updateTestMeta();
      };
    });
  }

  // ── Desk ──
  async function openDesk(id, show = true) {
    state.selectedId = id;
    try {
      const d = await req(`/admin/tenants/${id}`, { headers: headers(false) });
      state.desk = d;
      if (show) {
        $("desk").classList.remove("hidden");
        state.deskTab = "overview";
        document.querySelectorAll(".desk-tab").forEach((t) => {
          t.classList.toggle("active", t.dataset.tab === "overview");
        });
      }
      $("deskTitle").textContent = d.tenant.name;
      $("deskSub").textContent = `${d.tenant.status} · ${d.tenant.slug}`;
      renderDesk();
    } catch (e) {
      await notifyError("Could not open company", e.message);
    }
  }

  function renderDesk() {
    if (!state.desk) return;
    const tab = state.deskTab;
    document.querySelectorAll(".desk-pane").forEach((p) => p.classList.remove("active"));
    const pane = $("tab-" + tab);
    if (pane) pane.classList.add("active");
    if (tab === "overview") renderDeskOverview();
    if (tab === "settings") renderDeskSettings();
    if (tab === "keys") renderDeskKeys();
    if (tab === "docs") renderDeskDocs();
    if (tab === "models") renderDeskModels();
    if (tab === "usage") renderDeskUsage();
  }

  function integrationHtml(tenant, issuedKey) {
    const base = baseUrl();
    const pref = apiPrefix();
    const rows = [
      ["Base URL", base],
      ["Query", `POST ${base}${pref}/query`],
      ["Ingest file", `POST ${base}${pref}/ingest/file`],
      ["Auth", issuedKey ? `X-API-Key: ${issuedKey}` : "X-API-Key: <issue a key>"],
      ["Namespace", tenant.pinecone_namespace],
    ];
    return `<div class="integ-card">
      <h4>Client integration</h4>
      ${rows
        .map(
          ([label, val]) => `<div class="integ-row">
          <div class="integ-label">${esc(label)}</div>
          <div class="integ-value">${esc(val)}</div>
          <button type="button" class="btn sm" data-copy="${esc(val)}" data-label="${esc(label)}">Copy</button>
        </div>`
        )
        .join("")}
    </div>`;
  }

  function bindCopy(root) {
    root.querySelectorAll("[data-copy]").forEach((b) => {
      b.onclick = () => copyText(b.dataset.label || "value", b.dataset.copy);
    });
  }

  function renderDeskOverview() {
    const t = state.desk.tenant;
    const iso = state.desk.isolation || {};
    const issued = state.testKeys[t.id] || "";
    const el = $("tab-overview");
    el.innerHTML = `
      <div class="banner" style="margin-bottom:12px">
        <strong>Company isolation (hard silo)</strong>
        <p class="muted" style="margin:6px 0 0">
          Namespace <code class="mono">${esc(t.pinecone_namespace)}</code> ·
          S3 <code class="mono">${esc(iso.s3_prefix || "companies/" + t.slug + "/documents/")}</code><br/>
          Chat apps must use <strong>this company’s API key only</strong>. Never share keys across Core Tech / QuizForge / others.
        </p>
      </div>
      <div class="stat-grid">
        <div class="stat"><div class="lbl">Status</div><div class="val" style="font-size:1rem">${esc(t.status)}</div></div>
        <div class="stat"><div class="lbl">Keys</div><div class="val">${state.desk.keys?.length || 0}</div></div>
        <div class="stat"><div class="lbl">Documents</div><div class="val">${state.desk.documents?.length || 0}</div></div>
        <div class="stat"><div class="lbl">Queries</div><div class="val">${state.desk.query_count || 0}</div></div>
      </div>
      <div class="company-meta" style="margin-bottom:12px">
        Model: <strong>${esc(t.default_model || "—")}</strong> ·
        Rate: ${t.rate_limit_rpm}/min ·
        NS: <code class="mono">${esc(t.pinecone_namespace)}</code>
      </div>
      <div class="form-row">
        <button type="button" class="btn ${t.status === "active" ? "danger" : "primary"}" id="btnToggleStatus">
          <span class="btn-label">${t.status === "active" ? "Disable company" : "Enable company"}</span>
        </button>
        <button type="button" class="btn" id="btnDeskSettings">RAG settings</button>
        <button type="button" class="btn" id="btnDeskTest">Open Test API</button>
        <button type="button" class="btn" id="btnReindex">
          <span class="btn-label">Reindex all docs</span>
        </button>
      </div>
      ${integrationHtml(t, issued)}
    `;
    bindCopy(el);
    $("btnToggleStatus").onclick = async () => {
      const next = t.status === "active" ? "disabled" : "active";
      const ok = await confirmAction(
        next === "disabled" ? "Disable company?" : "Enable company?",
        `${t.name} will ${next === "disabled" ? "stop" : "resume"} accepting API calls.`,
        next === "disabled" ? "Disable" : "Enable"
      );
      if (!ok) return;
      const btn = $("btnToggleStatus");
      setBtnLoading(btn, true);
      try {
        await req(`/admin/tenants/${t.id}`, {
          method: "PATCH",
          headers: headers(true),
          body: JSON.stringify({ status: next }),
        });
        await notifySuccess("Status updated", `${t.name} is now ${next}.`);
        await refresh();
        await openDesk(t.id);
      } catch (e) {
        await notifyError("Update failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
    $("btnDeskSettings").onclick = () => {
      state.deskTab = "settings";
      document.querySelectorAll(".desk-tab").forEach((t) => {
        t.classList.toggle("active", t.dataset.tab === "settings");
      });
      renderDesk();
    };
    $("btnDeskTest").onclick = () => {
      $("desk").classList.add("hidden");
      document.querySelector('.nav-item[data-view="test"]').click();
      $("testCompany").value = t.id;
      updateTestMeta();
    };
    $("btnReindex").onclick = async () => {
      const ok = await confirmAction(
        "Reindex all documents?",
        `Re-embeds every file for ${t.name} into namespace ${t.pinecone_namespace}. Use this to fix mixed Core Tech / QuizForge answers.`,
        "Reindex"
      );
      if (!ok) return;
      const btn = $("btnReindex");
      setBtnLoading(btn, true, "Reindexing…");
      try {
        const d = await req(`/admin/tenants/${t.id}/documents/reindex`, {
          method: "POST",
          headers: headers(false),
        });
        const failN = (d.failed || []).length;
        await notifySuccess(
          "Reindex complete",
          `${d.message || ""}${failN ? `\nFailed: ${failN}` : ""}`
        );
        await openDesk(t.id);
        refresh();
      } catch (e) {
        await notifyError("Reindex failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
  }

  function valOr(v, fallback) {
    return v == null || v === "" ? "" : v;
  }

  function renderDeskSettings() {
    const t = state.desk.tenant;
    const defs = state.desk.rag_config?.defaults || {};
    const el = $("tab-settings");
    el.innerHTML = `
      <p class="muted" style="margin-top:0">Empty fields use platform defaults. Saved to Postgres for this company only.</p>

      <div class="settings-section">
        <h4>AI model &amp; API key</h4>
        <p class="sec-desc">
          Platform default uses env <code>OPENROUTER_API_KEY</code>. Override per company for a separate OpenRouter key and model.
        </p>
        <div class="form-grid">
          <label class="field">
            <span>OpenRouter model id</span>
            <input id="cfgModel" value="${esc(t.default_model || "")}" placeholder="${esc(
              defs.default_model || "openai/gpt-4o-mini"
            )}" />
            <span class="hint">Example: openai/gpt-4o-mini · empty = platform default</span>
          </label>
          <label class="field">
            <span>LLM base URL (optional)</span>
            <input id="cfgLlmBase" value="${esc(t.llm_base_url || "")}" placeholder="https://openrouter.ai/api/v1" />
          </label>
        </div>
        <label class="field" style="margin-top:10px">
          <span>Company OpenRouter API key</span>
          <input id="cfgLlmKey" type="password" autocomplete="off" placeholder="${
            t.llm_api_key_set
              ? "Key set (" + esc(t.llm_api_key_hint || "••••") + ") — paste new to replace"
              : "Empty = use platform OPENROUTER_API_KEY"
          }" />
          <span class="hint">
            ${
              t.llm_api_key_set
                ? "Using company key " + esc(t.llm_api_key_hint || "") + ". Leave blank and save to keep. Clear with Clear LLM key."
                : "Currently using platform key from env."
            }
          </span>
        </label>
        <div class="form-row" style="margin-top:8px">
          <button type="button" class="btn sm" id="btnClearLlmKey"><span class="btn-label">Clear company LLM key</span></button>
        </div>
      </div>

      <div class="settings-section">
        <h4>System prompt</h4>
        <p class="sec-desc">Instructions the LLM always follows for this company.</p>
        <label class="field">
          <span>System prompt</span>
          <textarea id="cfgPrompt" placeholder="Leave empty for default company knowledge assistant prompt…">${esc(
            t.system_prompt || ""
          )}</textarea>
          <span class="hint">Tip: tell the model tone, what it may answer, and what to refuse.</span>
        </label>
        <label class="field" style="margin-top:10px">
          <span>No-context message</span>
          <textarea id="cfgNoCtx" style="min-height:72px" placeholder="Message when retrieval finds nothing…">${esc(
            t.no_context_message || ""
          )}</textarea>
        </label>
      </div>

      <div class="settings-section">
        <h4>Retrieval</h4>
        <p class="sec-desc">How many chunks to fetch and keep for the answer.</p>
        <div class="form-grid">
          <label class="field">
            <span>top_k (retrieve)</span>
            <input id="cfgTopK" type="number" min="1" max="50" placeholder="${esc(
              defs.top_k ?? 10
            )}" value="${esc(valOr(t.top_k))}" />
            <span class="hint">Default ${esc(defs.top_k ?? 10)}</span>
          </label>
          <label class="field">
            <span>return_top_n (use in context)</span>
            <input id="cfgReturnN" type="number" min="1" max="20" placeholder="${esc(
              defs.return_top_n ?? 3
            )}" value="${esc(valOr(t.return_top_n))}" />
            <span class="hint">Default ${esc(defs.return_top_n ?? 3)}</span>
          </label>
          <label class="field">
            <span>min retrieval score</span>
            <input id="cfgMinScore" type="number" min="0" max="1" step="0.01" placeholder="${esc(
              defs.min_retrieval_score ?? 0.15
            )}" value="${esc(valOr(t.min_retrieval_score))}" />
          </label>
          <label class="field">
            <span>max chars / chunk</span>
            <input id="cfgChunkChars" type="number" min="100" max="4000" placeholder="${esc(
              defs.max_chars_per_chunk ?? 800
            )}" value="${esc(valOr(t.max_chars_per_chunk))}" />
          </label>
        </div>
        <div class="form-grid" style="margin-top:10px">
          <div class="switch-row">
            <div>
              <strong style="color:var(--text);font-size:.9rem">Rerank</strong>
              <div class="hint">Cross-encoder reordering before context build</div>
            </div>
            <label class="switch">
              <input type="checkbox" id="cfgRerank" ${
                t.rerank_enabled === false ? "" : "checked"
              } />
              <span></span>
            </label>
          </div>
          <div class="switch-row">
            <div>
              <strong style="color:var(--text);font-size:.9rem">Answer cache</strong>
              <div class="hint">Cache identical questions for this company</div>
            </div>
            <label class="switch">
              <input type="checkbox" id="cfgCache" ${
                t.answer_cache_enabled === false ? "" : "checked"
              } />
              <span></span>
            </label>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <h4>Token / length limits</h4>
        <p class="sec-desc">Controls context size and client question length.</p>
        <div class="form-grid">
          <label class="field">
            <span>max_context_chars</span>
            <input id="cfgCtx" type="number" min="500" max="32000" placeholder="${esc(
              defs.max_context_chars ?? 4000
            )}" value="${esc(valOr(t.max_context_chars))}" />
            <span class="hint">~ tokens ≈ chars / 4 · default ${esc(defs.max_context_chars ?? 4000)}</span>
          </label>
          <label class="field">
            <span>max_question_chars</span>
            <input id="cfgQ" type="number" min="50" max="20000" placeholder="${esc(
              defs.max_question_chars ?? 2000
            )}" value="${esc(valOr(t.max_question_chars))}" />
          </label>
          <label class="field">
            <span>temperature</span>
            <input id="cfgTemp" type="number" min="0" max="2" step="0.05" placeholder="${esc(
              defs.temperature ?? 0
            )}" value="${esc(valOr(t.temperature))}" />
          </label>
          <label class="field">
            <span>rate_limit_rpm</span>
            <input id="cfgRpm" type="number" min="1" max="10000" value="${esc(
              t.rate_limit_rpm ?? 60
            )}" />
          </label>
        </div>
      </div>

      <div class="settings-section">
        <h4>Notes</h4>
        <label class="field">
          <span>Internal notes (not sent to LLM)</span>
          <textarea id="cfgNotes" style="min-height:72px">${esc(t.notes || "")}</textarea>
        </label>
      </div>

      <div class="form-row">
        <button type="button" class="btn primary" id="btnSaveRag"><span class="btn-label">Save RAG settings</span></button>
        <button type="button" class="btn" id="btnResetRag"><span class="btn-label">Clear overrides</span></button>
      </div>
    `;

    $("btnClearLlmKey").onclick = async () => {
      const ok = await confirmAction(
        "Clear company LLM key?",
        "This company will use the platform OPENROUTER_API_KEY from env again.",
        "Clear key"
      );
      if (!ok) return;
      try {
        await req(`/admin/tenants/${t.id}/rag-settings`, {
          method: "PUT",
          headers: headers(true),
          body: JSON.stringify({ llm_api_key: null }),
        });
        await notifySuccess("LLM key cleared", "Platform OpenRouter key will be used.");
        await openDesk(t.id, false);
        state.deskTab = "settings";
        document.querySelectorAll(".desk-tab").forEach((x) => {
          x.classList.toggle("active", x.dataset.tab === "settings");
        });
        renderDesk();
      } catch (e) {
        await notifyError("Clear failed", e.message);
      }
    };

    $("btnSaveRag").onclick = async () => {
      const btn = $("btnSaveRag");
      setBtnLoading(btn, true, "Saving…");
      try {
        const num = (id) => {
          const v = $(id).value;
          if (v === "" || v == null) return null;
          return Number(v);
        };
        const body = {
          system_prompt: $("cfgPrompt").value || null,
          no_context_message: $("cfgNoCtx").value || null,
          notes: $("cfgNotes").value || null,
          default_model: $("cfgModel").value || null,
          llm_base_url: $("cfgLlmBase").value || null,
          top_k: num("cfgTopK"),
          return_top_n: num("cfgReturnN"),
          min_retrieval_score: num("cfgMinScore"),
          max_chars_per_chunk: num("cfgChunkChars"),
          max_context_chars: num("cfgCtx"),
          max_question_chars: num("cfgQ"),
          temperature: num("cfgTemp"),
          rate_limit_rpm: num("cfgRpm") ?? 60,
          rerank_enabled: $("cfgRerank").checked,
          answer_cache_enabled: $("cfgCache").checked,
        };
        const keyVal = ($("cfgLlmKey").value || "").trim();
        if (keyVal) body.llm_api_key = keyVal;
        await req(`/admin/tenants/${t.id}/rag-settings`, {
          method: "PUT",
          headers: headers(true),
          body: JSON.stringify(body),
        });
        await notifySuccess(
          "Settings saved",
          `RAG + AI model config for ${t.name} is stored. Next queries use this company's model/key when set.`
        );
        await openDesk(t.id, false);
        state.deskTab = "settings";
        document.querySelectorAll(".desk-tab").forEach((x) => {
          x.classList.toggle("active", x.dataset.tab === "settings");
        });
        renderDesk();
        flash("RAG settings saved");
      } catch (e) {
        await notifyError("Save failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };

    $("btnResetRag").onclick = async () => {
      const ok = await confirmAction(
        "Clear company overrides?",
        "System prompt, top_k, token limits and related fields will fall back to platform defaults.",
        "Clear"
      );
      if (!ok) return;
      const btn = $("btnResetRag");
      setBtnLoading(btn, true, "Clearing…");
      try {
        await req(`/admin/tenants/${t.id}/rag-settings`, {
          method: "PUT",
          headers: headers(true),
          body: JSON.stringify({
            system_prompt: null,
            no_context_message: null,
            top_k: null,
            return_top_n: null,
            min_retrieval_score: null,
            max_chars_per_chunk: null,
            max_context_chars: null,
            max_question_chars: null,
            temperature: null,
            rerank_enabled: null,
            answer_cache_enabled: null,
          }),
        });
        await notifySuccess("Overrides cleared", "This company now uses platform defaults.");
        await openDesk(t.id, false);
        state.deskTab = "settings";
        document.querySelectorAll(".desk-tab").forEach((x) => {
          x.classList.toggle("active", x.dataset.tab === "settings");
        });
        renderDesk();
      } catch (e) {
        await notifyError("Reset failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
  }

  function renderDeskKeys() {
    const t = state.desk.tenant;
    const keys = state.desk.keys || [];
    const el = $("tab-keys");
    el.innerHTML = `
      <div class="form-row">
        <label class="field grow"><span>Key name</span><input id="deskKeyName" value="production" /></label>
        <label class="field grow"><span>Scopes</span><input id="deskKeyScopes" value="query:read,ingest:write,docs:read" /></label>
        <button type="button" class="btn primary" id="deskIssueKey"><span class="btn-label">Issue key</span></button>
      </div>
      <div class="table-wrap" style="margin-top:12px">
        <table>
          <thead><tr><th>Name</th><th>Prefix</th><th>Scopes</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${keys
              .map(
                (k) => `<tr>
              <td>${esc(k.name)}</td>
              <td class="mono">${esc(k.key_prefix)}</td>
              <td>${esc((k.scopes || []).join(", "))}</td>
              <td><span class="badge ${k.status === "active" ? "ok" : "err"}">${esc(k.status)}</span></td>
              <td>${
                k.status === "active"
                  ? `<button class="btn sm danger" data-rev="${k.id}">Revoke</button>
                     <button class="btn sm" data-rot="${k.id}">Rotate</button>`
                  : ""
              }</td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;
    $("deskIssueKey").onclick = async () => {
      const btn = $("deskIssueKey");
      setBtnLoading(btn, true, "Issuing…");
      try {
        const scopes = $("deskKeyScopes")
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        const d = await req(`/admin/tenants/${t.id}/keys`, {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({ name: $("deskKeyName").value || "production", scopes }),
        });
        state.testKeys[t.id] = d.api_key;
        sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
        await notifySuccess("API key issued", "Copy the key now. It will not be shown again.", d.api_key);
        await openDesk(t.id);
      } catch (e) {
        await notifyError("Issue key failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
    el.querySelectorAll("[data-rev]").forEach((b) => {
      b.onclick = async () => {
        if (!(await confirmAction("Revoke key?", "This key stops working immediately.", "Revoke")))
          return;
        setBtnLoading(b, true);
        try {
          await req(`/admin/keys/${b.dataset.rev}/revoke`, { method: "POST", headers: headers(false) });
          await notifySuccess("Key revoked", "The key is no longer active.");
          await openDesk(t.id);
          refresh();
        } catch (e) {
          await notifyError("Revoke failed", e.message);
        } finally {
          setBtnLoading(b, false);
        }
      };
    });
    el.querySelectorAll("[data-rot]").forEach((b) => {
      b.onclick = async () => {
        if (!(await confirmAction("Rotate key?", "Old key dies. New secret shown once.", "Rotate")))
          return;
        setBtnLoading(b, true, "…");
        try {
          const d = await req(`/admin/keys/${b.dataset.rot}/rotate`, {
            method: "POST",
            headers: headers(false),
          });
          state.testKeys[t.id] = d.api_key;
          sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
          await notifySuccess("Key rotated", "Copy the new key now.", d.api_key);
          await openDesk(t.id);
        } catch (e) {
          await notifyError("Rotate failed", e.message);
        } finally {
          setBtnLoading(b, false);
        }
      };
    });
  }

  function renderDeskDocs() {
    const t = state.desk.tenant;
    const docs = state.desk.documents || [];
    const el = $("tab-docs");
    el.innerHTML = `
      <div class="banner" style="margin-bottom:12px">
        <strong>Docs for this company only</strong>
        <p class="muted" style="margin:6px 0 0">
          Vectors go to namespace <code class="mono">${esc(t.pinecone_namespace || "")}</code>.
          Do not upload another company's files here.
        </p>
      </div>
      <div class="form-row">
        <label class="field grow"><span>Upload files (multi-select bulk)</span>
          <input type="file" id="deskFile" accept=".pdf,.md,.txt,.markdown" multiple />
        </label>
        <button type="button" class="btn primary" id="deskUpload"><span class="btn-label">Upload &amp; embed</span></button>
        <button type="button" class="btn" id="deskReindex"><span class="btn-label">Reindex all</span></button>
      </div>
      <p class="muted" style="margin:8px 0 0;font-size:.82rem">Select many PDFs/MD/TXT — each embeds into this company namespace only.</p>
      <div id="bulkProgress" class="muted hidden" style="margin-top:8px"></div>
      <div class="table-wrap" style="margin-top:12px">
        <table>
          <thead><tr><th>File</th><th>Status</th><th>Vectors</th><th></th></tr></thead>
          <tbody>
            ${
              docs.length
                ? docs
                    .map(
                      (d) => `<tr>
              <td>${esc(d.filename)}</td>
              <td><span class="badge ${
                d.status === "ready" ? "ok" : d.status === "failed" ? "err" : "warn"
              }">${esc(d.status)}</span></td>
              <td>${d.vector_count ?? 0}</td>
              <td>
                <button class="btn sm" data-re="${d.id}">Reprocess</button>
                <button class="btn sm danger" data-del="${d.id}">Delete</button>
              </td>
            </tr>`
                    )
                    .join("")
                : `<tr><td colspan="4" class="muted">No documents yet</td></tr>`
            }
          </tbody>
        </table>
      </div>`;
    $("deskUpload").onclick = async () => {
      const list = $("deskFile").files;
      if (!list || !list.length) {
        await notifyError("No files", "Choose one or more PDF, Markdown, or text files.");
        return;
      }
      const btn = $("deskUpload");
      const prog = $("bulkProgress");
      setBtnLoading(btn, true, list.length > 1 ? `Embedding 0/${list.length}…` : "Uploading…");
      prog.classList.remove("hidden");
      prog.textContent = `Starting bulk upload (${list.length} file(s))…`;
      pushBusy(1);
      try {
        const fd = new FormData();
        for (let i = 0; i < list.length; i++) {
          fd.append("files", list[i]);
        }
        // Single file still uses bulk endpoint for consistent path
        const r = await fetch(api + `/admin/tenants/${t.id}/documents/bulk`, {
          method: "POST",
          headers: headers(false),
          body: fd,
        });
        const d = await r.json();
        if (!r.ok) throw new Error(formatError(d.detail || d.message, "upload failed"));
        const failedItems = (d.items || []).filter((x) => x.status === "failed");
        prog.textContent = d.message || `Done: ${d.succeeded}/${d.total}`;
        let msg = d.message || `Uploaded ${d.succeeded}/${d.total}`;
        if (failedItems.length) {
          msg +=
            "\n\nFailed:\n" +
            failedItems.map((x) => `• ${x.filename}: ${x.error || "error"}`).join("\n");
        }
        msg += `\nNamespace: ${d.pinecone_namespace || t.pinecone_namespace}`;
        await notifySuccess(
          d.failed ? "Bulk upload partial" : "Bulk upload complete",
          msg
        );
        await openDesk(t.id);
        refresh();
      } catch (e) {
        prog.textContent = "Failed: " + e.message;
        await notifyError("Upload failed", e.message);
      } finally {
        pushBusy(-1);
        setBtnLoading(btn, false);
      }
    };
    $("deskReindex").onclick = async () => {
      const ok = await confirmAction(
        "Reindex all documents?",
        `All files for ${t.name} will be re-embedded into ${t.pinecone_namespace}.`,
        "Reindex"
      );
      if (!ok) return;
      const btn = $("deskReindex");
      setBtnLoading(btn, true, "Reindexing…");
      try {
        const d = await req(`/admin/tenants/${t.id}/documents/reindex`, {
          method: "POST",
          headers: headers(false),
        });
        await notifySuccess("Reindex complete", d.message || "Done");
        await openDesk(t.id);
      } catch (e) {
        await notifyError("Reindex failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
    el.querySelectorAll("[data-re]").forEach((b) => {
      b.onclick = async () => {
        setBtnLoading(b, true);
        try {
          await req(`/admin/documents/${b.dataset.re}/reprocess`, {
            method: "POST",
            headers: headers(false),
          });
          await notifySuccess("Reprocessed", "Document re-embedded into the vector index.");
          await openDesk(t.id);
        } catch (e) {
          await notifyError("Reprocess failed", e.message);
        } finally {
          setBtnLoading(b, false);
        }
      };
    });
    el.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = async () => {
        if (!(await confirmAction("Delete document?", "Vectors will be removed.", "Delete"))) return;
        setBtnLoading(b, true);
        try {
          await req(`/admin/documents/${b.dataset.del}`, {
            method: "DELETE",
            headers: headers(false),
          });
          await notifySuccess("Deleted", "Document and vectors removed.");
          await openDesk(t.id);
          refresh();
        } catch (e) {
          await notifyError("Delete failed", e.message);
        } finally {
          setBtnLoading(b, false);
        }
      };
    });
  }

  function renderDeskModels() {
    const t = state.desk.tenant;
    const el = $("tab-models");
    el.innerHTML = `
      <div class="settings-section">
        <h4>Company AI (OpenRouter)</h4>
        <p class="sec-desc">Each company can use its own model id and API key. Empty key = platform env key.</p>
        <label class="field"><span>Model id</span>
          <input id="deskModel" value="${esc(t.default_model || "")}" placeholder="openai/gpt-4o-mini" />
        </label>
        <label class="field" style="margin-top:10px"><span>LLM base URL (optional)</span>
          <input id="deskLlmBase" value="${esc(t.llm_base_url || "")}" placeholder="https://openrouter.ai/api/v1" />
        </label>
        <label class="field" style="margin-top:10px"><span>OpenRouter API key for this company</span>
          <input id="deskLlmKey" type="password" autocomplete="off" placeholder="${
            t.llm_api_key_set
              ? "Key set (" + esc(t.llm_api_key_hint || "") + ") — paste new to replace"
              : "Leave empty to use platform OPENROUTER_API_KEY"
          }" />
        </label>
        <div class="form-row" style="margin-top:12px">
          <button type="button" class="btn primary" id="deskSaveModel">
            <span class="btn-label">Save AI model &amp; key</span>
          </button>
          <button type="button" class="btn" id="deskClearKey">
            <span class="btn-label">Clear company key</span>
          </button>
        </div>
        <p class="muted" style="margin-top:10px">
          Status: ${
            t.llm_api_key_set
              ? "Using <strong>company</strong> key " + esc(t.llm_api_key_hint || "")
              : "Using <strong>platform</strong> OPENROUTER_API_KEY"
          }
        </p>
      </div>`;
    $("deskSaveModel").onclick = async () => {
      const btn = $("deskSaveModel");
      setBtnLoading(btn, true, "Saving…");
      try {
        const body = {
          default_model: $("deskModel").value || null,
          llm_base_url: $("deskLlmBase").value || null,
        };
        const k = ($("deskLlmKey").value || "").trim();
        if (k) body.llm_api_key = k;
        await req(`/admin/tenants/${t.id}/rag-settings`, {
          method: "PUT",
          headers: headers(true),
          body: JSON.stringify(body),
        });
        await notifySuccess("AI config saved", `Model/key for ${t.name} updated.`);
        await openDesk(t.id);
        refresh();
      } catch (e) {
        await notifyError("Save failed", e.message);
      } finally {
        setBtnLoading(btn, false);
      }
    };
    $("deskClearKey").onclick = async () => {
      if (
        !(await confirmAction(
          "Clear company LLM key?",
          "Fall back to platform OPENROUTER_API_KEY.",
          "Clear"
        ))
      )
        return;
      try {
        await req(`/admin/tenants/${t.id}/rag-settings`, {
          method: "PUT",
          headers: headers(true),
          body: JSON.stringify({ llm_api_key: null }),
        });
        await notifySuccess("Key cleared", "Platform key will be used.");
        await openDesk(t.id);
      } catch (e) {
        await notifyError("Clear failed", e.message);
      }
    };
  }

  async function renderDeskUsage() {
    const t = state.desk.tenant;
    const el = $("tab-usage");
    el.innerHTML = `<p class="muted">Loading usage…</p>`;
    try {
      const e = await req(`/admin/usage/events?limit=40&tenant_id=${t.id}`, {
        headers: headers(false),
      });
      el.innerHTML = `
        <div class="stat-grid">
          <div class="stat"><div class="lbl">Queries (lifetime)</div><div class="val">${
            state.desk.query_count || 0
          }</div></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Type</th><th>Latency</th><th>Lag</th><th>Model</th></tr></thead>
            <tbody>
              ${(e.items || [])
                .map(
                  (x) => `<tr>
                <td>${esc(x.created_at)}</td>
                <td>${esc(x.event_type)}</td>
                <td>${x.latency_ms ?? "—"}</td>
                <td>${esc(x.lag_stage || "—")}</td>
                <td>${esc(x.model || "—")}</td>
              </tr>`
                )
                .join("") || `<tr><td colspan="5" class="muted">No events yet</td></tr>`}
            </tbody>
          </table>
        </div>`;
    } catch (err) {
      el.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    }
  }

  document.querySelectorAll(".desk-tab").forEach((tab) => {
    tab.onclick = () => {
      state.deskTab = tab.dataset.tab;
      document.querySelectorAll(".desk-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      renderDesk();
    };
  });
  $("deskClose").onclick = () => $("desk").classList.add("hidden");
  $("deskBackdrop").onclick = () => $("desk").classList.add("hidden");

  // ── Test ──
  function renderTestCompanySelect() {
    const sel = $("testCompany");
    const cur = sel.value;
    sel.innerHTML =
      `<option value="">Select company…</option>` +
      state.tenants
        .map((t) => `<option value="${t.id}">${esc(t.name)} (${esc(t.slug)})</option>`)
        .join("");
    if (cur) sel.value = cur;
    updateTestMeta();
  }

  function updateTestMeta() {
    const id = $("testCompany").value;
    const t = state.tenants.find((x) => x.id === id);
    if (!t) {
      $("testMeta").textContent = "No company selected";
      return;
    }
    const k = state.testKeys[id];
    $("testMeta").innerHTML = `NS <code class="mono">${esc(
      t.pinecone_namespace
    )}</code> · Model ${esc(t.default_model || "—")} · top_k ${
      t.top_k ?? "default"
    } · key: ${k ? `<code class="mono">${esc(k.slice(0, 18))}…</code>` : "<em>not issued</em>"}`;
  }
  $("testCompany").onchange = updateTestMeta;

  $("btnTestKey").onclick = async () => {
    const id = $("testCompany").value;
    if (!id) {
      await notifyError("Select a company", "Choose a company first.");
      return;
    }
    const btn = $("btnTestKey");
    setBtnLoading(btn, true, "Issuing…");
    try {
      const d = await req(`/admin/tenants/${id}/keys`, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          name: "admin-test",
          scopes: ["query:read", "ingest:write", "docs:read"],
        }),
      });
      state.testKeys[id] = d.api_key;
      sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
      updateTestMeta();
      await notifySuccess("Test key ready", "Kept for this browser session.", d.api_key);
      await refresh();
    } catch (e) {
      await notifyError("Could not issue test key", e.message);
    } finally {
      setBtnLoading(btn, false);
    }
  };

  function renderTestMessages() {
    const box = $("testMessages");
    if (!state.testMessages.length) {
      box.innerHTML =
        '<div class="empty-hint">Select a company, issue a test key, then ask a question.</div>';
      return;
    }
    box.innerHTML = state.testMessages
      .map((m) => {
        if (m.role === "user") return `<div class="bubble user">${esc(m.content)}</div>`;
        const chips = [
          m.lag_stage && `lag: ${m.lag_stage}`,
          m.total != null && `${m.total}ms`,
          m.model,
          m.cache_hit && `cache: ${m.cache_hit}`,
        ]
          .filter(Boolean)
          .map((c) => `<span class="chip">${esc(c)}</span>`)
          .join("");
        const src = (m.sources || [])
          .slice(0, 3)
          .map((s) => `<div>• ${esc((s.content || "").slice(0, 140))}</div>`)
          .join("");
        return `<div class="bubble assistant">${esc(m.content)}
          ${chips ? `<div class="chips">${chips}</div>` : ""}
          ${src ? `<div class="sources"><strong>Sources</strong>${src}</div>` : ""}
        </div>`;
      })
      .join("");
    box.scrollTop = box.scrollHeight;
  }

  $("testForm").onsubmit = async (ev) => {
    ev.preventDefault();
    const id = $("testCompany").value;
    const q = $("testQuestion").value.trim();
    if (!id) {
      await notifyError("Select a company", "Pick a company first.");
      return;
    }
    if (!q) return;
    const key = state.testKeys[id];
    if (!key) {
      await notifyError("No test key", "Click “Issue / refresh test key” first.");
      return;
    }
    state.testMessages.push({ role: "user", content: q });
    $("testQuestion").value = "";
    renderTestMessages();
    const btn = $("btnTestSend");
    setBtnLoading(btn, true, "…");
    pushBusy(1);
    try {
      const r = await fetch(api + "/query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": key },
        body: JSON.stringify({ question: q, include_timings: true }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(formatError(d.detail || d.message, r.statusText));
      state.testMessages.push({
        role: "assistant",
        content: d.answer || "(empty)",
        sources: d.sources,
        lag_stage: d.lag_stage,
        total: d.timings_ms?.total,
        model: d.model,
        cache_hit: d.cache_hit,
      });
      renderTestMessages();
    } catch (e) {
      state.testMessages.push({ role: "assistant", content: "Error: " + e.message });
      renderTestMessages();
      await notifyError("Query failed", e.message);
    } finally {
      pushBusy(-1);
      setBtnLoading(btn, false);
    }
  };

  // ── System ──
  async function renderSystem() {
    const integ = state.setup?.integrations || {};
    const items = [
      ["Database", integ.database, integ.database_url_scheme],
      ["Storage", integ.storage, integ.storage_backend],
      ["OpenRouter", integ.openrouter, "LLM"],
      ["Pinecone", integ.pinecone, "vectors"],
      ["Auth", integ.auth_enabled, integ.auth_enabled ? "on" : "off"],
    ];
    $("integGrid").innerHTML = items
      .map(
        ([name, ok, extra]) => `<div class="integ-item">
        <div class="name">${esc(name)}</div>
        <div class="state" style="color:${ok ? "var(--ok)" : "var(--err)"}">${
          ok ? "Connected" : "Not ready"
        }</div>
        <div class="muted" style="font-size:.75rem;margin-top:4px">${esc(extra || "")}</div>
      </div>`
      )
      .join("");
    try {
      const m = await req("/admin/models", { headers: headers(false) });
      $("embedInfo").textContent = `Embedding: ${m.embedding?.model || "—"} (dim ${
        m.embedding?.dimension || "—"
      })`;
      $("modelChips").innerHTML = (m.items || [])
        .map(
          (x) =>
            `<button type="button" class="model-chip ${x.is_default ? "default" : ""}" data-mid="${esc(
              x.model_id
            )}">${esc(x.label)}${x.is_default ? " · default" : ""}</button>`
        )
        .join("");
      $("modelChips").querySelectorAll("[data-mid]").forEach((b) => {
        b.onclick = () => {
          $("sysModel").value = b.dataset.mid;
        };
      });
    } catch {
      /* ignore */
    }
  }

  $("btnSaveModel").onclick = async () => {
    const btn = $("btnSaveModel");
    setBtnLoading(btn, true, "Saving…");
    try {
      await req("/admin/models/default", {
        method: "PUT",
        headers: headers(true),
        body: JSON.stringify({ model_id: $("sysModel").value }),
      });
      await notifySuccess("Default model saved", "Platform catalog default updated.");
      renderSystem();
    } catch (e) {
      await notifyError("Save failed", e.message);
    } finally {
      setBtnLoading(btn, false);
    }
  };

  // ── Add company ──
  function openAddModal() {
    $("modalAdd").classList.remove("hidden");
    $("mName").value = "";
  }
  $("btnAddCompany").onclick = openAddModal;
  $("btnAddCompany2").onclick = openAddModal;
  $("mCancel").onclick = () => $("modalAdd").classList.add("hidden");
  $("mSave").onclick = async () => {
    const name = ($("mName").value || "").trim();
    if (!name) {
      await notifyError("Name required", "Enter a company name.");
      return;
    }
    const btn = $("mSave");
    setBtnLoading(btn, true, "Creating…");
    try {
      const d = await req("/admin/onboard", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          company_name: name,
          key_name: $("mKeyName").value || "production",
          default_model: $("mModel").value || null,
        }),
      });
      state.testKeys[d.tenant.id] = d.api_key;
      sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
      $("modalAdd").classList.add("hidden");
      await notifySuccess(
        "Company created",
        `${d.tenant.name} is ready. Copy the API key, then open RAG settings.`,
        d.api_key
      );
      await refresh();
      openDesk(d.tenant.id);
    } catch (e) {
      await notifyError("Onboard failed", e.message);
    } finally {
      setBtnLoading(btn, false);
    }
  };

  $("companySearch").oninput = renderCompanies;
  $("btnRefresh").onclick = async () => {
    const btn = $("btnRefresh");
    setBtnLoading(btn, true, "…");
    try {
      await refresh();
      flash("Refreshed");
    } finally {
      setBtnLoading(btn, false);
    }
  };

  $("modalDialog").addEventListener("click", (ev) => {
    if (ev.target === $("modalDialog") && dlgResolve) closeDialog(false);
  });

  (async function boot() {
    const stored = cleanKey(localStorage.getItem(STORAGE_KEY) || "");
    $("gateKey").value = stored;
    const ok = await connectWithKey(stored, { silent: true });
    if (!ok) setConnectedUI(false);
  })();
})();
