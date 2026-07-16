(() => {
  const $ = (id) => document.getElementById(id);
  const api = "/api/v1";
  const titles = {
    home: ["Home", "Setup checklist — live from Postgres"],
    companies: ["Companies", "Client companies (tenants). Configure keys, docs, models per company."],
    test: ["Test API", "Pick a company and chat with a real tenant API key"],
    users: ["Users", "Operators stored in the database"],
    system: ["System", "Integrations and platform model defaults"],
  };

  const state = {
    tenants: [],
    users: [],
    setup: null,
    config: null,
    selectedId: null,
    desk: null,
    deskTab: "overview",
    testKeys: JSON.parse(sessionStorage.getItem("rag_test_keys") || "{}"),
    testMessages: [],
  };

  const keyEl = $("apiKey");
  keyEl.value = localStorage.getItem("rag_admin_key") || "dev-admin-key";
  keyEl.onchange = () => localStorage.setItem("rag_admin_key", keyEl.value.trim());

  function headers(json = true) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    const k = keyEl.value.trim();
    if (k) h["X-API-Key"] = k;
    return h;
  }

  async function req(path, opts = {}) {
    const r = await fetch(api + path, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = d.detail || d.message || r.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return d;
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function toast(msg, ok = true) {
    const el = $("toast");
    el.className = "toast " + (ok ? "ok" : "err");
    el.textContent = msg;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 3200);
  }

  async function copyText(label, value) {
    try {
      await navigator.clipboard.writeText(value);
      toast(`Copied ${label}`);
    } catch {
      toast("Copy failed — select text manually", false);
    }
  }

  function baseUrl() {
    const fromEnv = (state.config?.public_base_url || state.setup?.public_base_url || "").trim();
    return (fromEnv || window.location.origin).replace(/\/$/, "");
  }

  function apiPrefix() {
    return state.config?.api_prefix || state.setup?.api_prefix || "/api/v1";
  }

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

  // ── loaders ──
  async function refresh() {
    try {
      const [dash, conf, tenants, users] = await Promise.all([
        req("/admin/dashboard", { headers: headers(false) }),
        req("/admin/system/config", { headers: headers(false) }),
        req("/admin/tenants", { headers: headers(false) }),
        req("/admin/users", { headers: headers(false) }),
      ]);
      state.setup = dash.setup;
      state.config = conf;
      state.tenants = tenants.items || [];
      state.users = users.items || [];
      renderHome();
      renderCompanies();
      renderUsers();
      renderSystem();
      renderTestCompanySelect();
      if (state.selectedId) await openDesk(state.selectedId, false);
      const integ = state.setup?.integrations || {};
      const ok = integ.database && integ.openrouter && integ.pinecone;
      $("statusPill").className = "pill " + (ok ? "ok" : "warn");
      $("statusPill").textContent = ok ? "core ready" : "setup needed";
    } catch (e) {
      $("statusPill").className = "pill err";
      $("statusPill").textContent = "auth / server error";
      $("nextBox").textContent =
        "Cannot reach admin API. Check platform admin key and server. " + e.message;
      toast(e.message, false);
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
      nb.innerHTML = "<strong>Setup complete.</strong> Use Companies → Configure to manage each client.";
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
      ["Users", counts.users ?? 0],
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
          Keys: ${t.keys_active ?? 0} · Docs: ${t.documents_ready ?? 0}/${t.documents ?? 0} ready · Queries: ${t.query_count ?? 0}
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

  // ── Company desk ──
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
      $("deskSub").textContent = `${d.tenant.status} · ${d.tenant.slug} · ${d.tenant.id}`;
      renderDesk();
    } catch (e) {
      toast(e.message, false);
    }
  }

  function renderDesk() {
    const d = state.desk;
    if (!d) return;
    const tab = state.deskTab;
    document.querySelectorAll(".desk-pane").forEach((p) => p.classList.remove("active"));
    $("tab-" + tab).classList.add("active");
    if (tab === "overview") renderDeskOverview();
    if (tab === "keys") renderDeskKeys();
    if (tab === "docs") renderDeskDocs();
    if (tab === "models") renderDeskModels();
    if (tab === "members") renderDeskMembers();
    if (tab === "usage") renderDeskUsage();
  }

  function integrationHtml(tenant, issuedKey) {
    const base = baseUrl();
    const pref = apiPrefix();
    const rows = [
      ["Base URL", base],
      ["Query", `POST ${base}${pref}/query`],
      ["Ingest file", `POST ${base}${pref}/ingest/file`],
      ["Documents", `GET ${base}${pref}/documents`],
      ["Auth header", issuedKey ? `X-API-Key: ${issuedKey}` : "X-API-Key: <issue a key>"],
      ["Namespace", tenant.pinecone_namespace],
      [
        "Sample curl",
        `curl -s -X POST "${base}${pref}/query" -H "X-API-Key: ${
          issuedKey || "<KEY>"
        }" -H "Content-Type: application/json" -d "{\\"question\\":\\"What is the leave policy?\\"}"`,
      ],
    ];
    return `<div class="integ-card">
      <h4>Client integration (copy &amp; share)</h4>
      ${rows
        .map(
          ([label, val], i) => `<div class="integ-row">
          <div class="integ-label">${esc(label)}</div>
          <div class="integ-value" id="integ-val-${i}">${esc(val)}</div>
          <button type="button" class="btn sm" data-copy="${esc(val)}" data-label="${esc(
            label
          )}">Copy</button>
        </div>`
        )
        .join("")}
      <p class="muted" style="margin:10px 0 0;font-size:.78rem">
        Full API secret is only available when you issue or rotate a key. Later lists show prefix only.
      </p>
    </div>`;
  }

  function bindCopy(root) {
    root.querySelectorAll("[data-copy]").forEach((b) => {
      b.onclick = () => copyText(b.dataset.label || "value", b.dataset.copy);
    });
  }

  function renderDeskOverview() {
    const t = state.desk.tenant;
    const issued = state.testKeys[t.id] || "";
    const el = $("tab-overview");
    el.innerHTML = `
      <div class="stat-grid">
        <div class="stat"><div class="lbl">Status</div><div class="val" style="font-size:1rem">${esc(
          t.status
        )}</div></div>
        <div class="stat"><div class="lbl">Keys</div><div class="val">${
          state.desk.keys?.length || 0
        }</div></div>
        <div class="stat"><div class="lbl">Documents</div><div class="val">${
          state.desk.documents?.length || 0
        }</div></div>
        <div class="stat"><div class="lbl">Queries</div><div class="val">${
          state.desk.query_count || 0
        }</div></div>
      </div>
      <div class="company-meta" style="margin-bottom:10px">
        Model: <strong>${esc(t.default_model || "—")}</strong> ·
        Rate limit: ${t.rate_limit_rpm}/min ·
        Namespace: <code class="mono">${esc(t.pinecone_namespace)}</code>
      </div>
      <div class="form-row">
        <button type="button" class="btn ${
          t.status === "active" ? "danger" : "primary"
        }" id="btnToggleStatus">${
      t.status === "active" ? "Disable company" : "Enable company"
    }</button>
        <button type="button" class="btn" id="btnDeskTest">Open Test API</button>
      </div>
      ${integrationHtml(t, issued)}
    `;
    bindCopy(el);
    $("btnToggleStatus").onclick = async () => {
      try {
        await req(`/admin/tenants/${t.id}`, {
          method: "PATCH",
          headers: headers(true),
          body: JSON.stringify({
            status: t.status === "active" ? "disabled" : "active",
          }),
        });
        toast("Company status updated");
        await refresh();
        await openDesk(t.id);
      } catch (e) {
        toast(e.message, false);
      }
    };
    $("btnDeskTest").onclick = () => {
      $("desk").classList.add("hidden");
      document.querySelector('.nav-item[data-view="test"]').click();
      $("testCompany").value = t.id;
      updateTestMeta();
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
        <button type="button" class="btn primary" id="deskIssueKey">Issue key</button>
      </div>
      <div id="deskKeySecret" class="secret-box hidden"></div>
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
              <td><span class="badge ${k.status === "active" ? "ok" : "err"}">${esc(
                  k.status
                )}</span></td>
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
      try {
        const scopes = $("deskKeyScopes").value.split(",").map((s) => s.trim()).filter(Boolean);
        const d = await req(`/admin/tenants/${t.id}/keys`, {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({ name: $("deskKeyName").value || "production", scopes }),
        });
        state.testKeys[t.id] = d.api_key;
        sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
        const box = $("deskKeySecret");
        box.classList.remove("hidden");
        box.innerHTML = `<strong>COPY KEY NOW (once)</strong><br/>${esc(d.api_key)}
          <br/><button type="button" class="btn sm" style="margin-top:8px" id="copyNewKey">Copy key</button>`;
        $("copyNewKey").onclick = () => copyText("API key", d.api_key);
        toast("Key issued");
        await openDesk(t.id);
      } catch (e) {
        toast(e.message, false);
      }
    };
    el.querySelectorAll("[data-rev]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Revoke this key?")) return;
        try {
          await req(`/admin/keys/${b.dataset.rev}/revoke`, {
            method: "POST",
            headers: headers(false),
          });
          toast("Key revoked");
          await openDesk(t.id);
          refresh();
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
    el.querySelectorAll("[data-rot]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Rotate key? Old key stops working.")) return;
        try {
          const d = await req(`/admin/keys/${b.dataset.rot}/rotate`, {
            method: "POST",
            headers: headers(false),
          });
          state.testKeys[t.id] = d.api_key;
          sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
          const box = $("deskKeySecret");
          box.classList.remove("hidden");
          box.innerHTML = `<strong>NEW KEY (copy once)</strong><br/>${esc(d.api_key)}`;
          toast("Key rotated");
          await openDesk(t.id);
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
  }

  function renderDeskDocs() {
    const t = state.desk.tenant;
    const docs = state.desk.documents || [];
    const el = $("tab-docs");
    el.innerHTML = `
      <div class="form-row">
        <label class="field grow"><span>Upload file for this company</span>
          <input type="file" id="deskFile" accept=".pdf,.md,.txt,.markdown" />
        </label>
        <button type="button" class="btn primary" id="deskUpload">Upload &amp; embed</button>
      </div>
      <div class="table-wrap">
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
      const f = $("deskFile").files?.[0];
      if (!f) return toast("Choose a file", false);
      const fd = new FormData();
      fd.append("file", f);
      try {
        const r = await fetch(api + `/admin/tenants/${t.id}/documents`, {
          method: "POST",
          headers: headers(false),
          body: fd,
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || d.message || "upload failed");
        toast(`Document ${d.document?.status || "uploaded"}`);
        await openDesk(t.id);
        refresh();
      } catch (e) {
        toast(e.message, false);
      }
    };
    el.querySelectorAll("[data-re]").forEach((b) => {
      b.onclick = async () => {
        try {
          await req(`/admin/documents/${b.dataset.re}/reprocess`, {
            method: "POST",
            headers: headers(false),
          });
          toast("Reprocessed");
          await openDesk(t.id);
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
    el.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Delete document?")) return;
        try {
          await req(`/admin/documents/${b.dataset.del}`, {
            method: "DELETE",
            headers: headers(false),
          });
          toast("Deleted");
          await openDesk(t.id);
          refresh();
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
  }

  function renderDeskModels() {
    const t = state.desk.tenant;
    const el = $("tab-models");
    el.innerHTML = `
      <label class="field"><span>LLM for this company (OpenRouter model id)</span>
        <input id="deskModel" value="${esc(t.default_model || "")}" placeholder="openai/gpt-4o-mini" />
      </label>
      <button type="button" class="btn primary" id="deskSaveModel" style="margin-top:10px">Save model</button>
      <p class="muted" style="margin-top:10px">Queries for this tenant use this model when set.</p>`;
    $("deskSaveModel").onclick = async () => {
      try {
        await req(`/admin/tenants/${t.id}/models`, {
          method: "PATCH",
          headers: headers(true),
          body: JSON.stringify({ model_id: $("deskModel").value }),
        });
        toast("Model updated");
        await openDesk(t.id);
        refresh();
      } catch (e) {
        toast(e.message, false);
      }
    };
  }

  async function renderDeskMembers() {
    const t = state.desk.tenant;
    const el = $("tab-members");
    el.innerHTML = `<p class="muted">Loading members…</p>`;
    try {
      const m = await req(`/admin/tenants/${t.id}/members`, { headers: headers(false) });
      el.innerHTML = `
        <div class="form-row">
          <label class="field grow"><span>User</span>
            <select id="deskUserSel">${state.users
              .map((u) => `<option value="${u.id}">${esc(u.full_name)} (${esc(u.email)})</option>`)
              .join("")}</select>
          </label>
          <label class="field"><span>Role</span>
            <select id="deskMemRole">
              <option value="tenant_member">tenant_member</option>
              <option value="tenant_admin">tenant_admin</option>
            </select>
          </label>
          <button type="button" class="btn primary" id="deskAssign">Assign</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th></th></tr></thead>
            <tbody>
              ${(m.items || [])
                .map(
                  (x) => `<tr>
                <td>${esc(x.full_name)}</td>
                <td>${esc(x.email)}</td>
                <td>${esc(x.role)}</td>
                <td><button class="btn sm danger" data-rm="${x.id}">Remove</button></td>
              </tr>`
                )
                .join("") || `<tr><td colspan="4" class="muted">No members</td></tr>`}
            </tbody>
          </table>
        </div>`;
      $("deskAssign").onclick = async () => {
        try {
          await req("/admin/users/assign", {
            method: "POST",
            headers: headers(true),
            body: JSON.stringify({
              user_id: $("deskUserSel").value,
              tenant_id: t.id,
              role: $("deskMemRole").value,
            }),
          });
          toast("User assigned");
          renderDeskMembers();
        } catch (e) {
          toast(e.message, false);
        }
      };
      el.querySelectorAll("[data-rm]").forEach((b) => {
        b.onclick = async () => {
          try {
            await req(`/admin/tenants/${t.id}/members/${b.dataset.rm}`, {
              method: "DELETE",
              headers: headers(false),
            });
            toast("Removed");
            renderDeskMembers();
          } catch (e) {
            toast(e.message, false);
          }
        };
      });
    } catch (e) {
      el.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
    }
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

  // desk tabs
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

  // ── Test API ──
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
    $("testMeta").innerHTML = `Namespace <code class="mono">${esc(
      t.pinecone_namespace
    )}</code> · Model ${esc(t.default_model || "—")} · Test key: ${
      k ? `<code class="mono">${esc(k.slice(0, 18))}…</code> (session)` : "<em>not issued yet</em>"
    }`;
  }

  $("testCompany").onchange = updateTestMeta;

  $("btnTestKey").onclick = async () => {
    const id = $("testCompany").value;
    if (!id) return toast("Select a company", false);
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
      toast("Test key ready for this session");
      await refresh();
    } catch (e) {
      toast(e.message, false);
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
        if (m.role === "user") {
          return `<div class="bubble user">${esc(m.content)}</div>`;
        }
        const chips = [
          m.lag_stage && `lag: ${m.lag_stage}`,
          m.total != null && `${m.total}ms`,
          m.model && m.model,
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
    if (!id) return toast("Select a company", false);
    if (!q) return;
    let key = state.testKeys[id];
    if (!key) {
      toast("Issue a test key first", false);
      return;
    }
    state.testMessages.push({ role: "user", content: q });
    $("testQuestion").value = "";
    renderTestMessages();
    $("btnTestSend").disabled = true;
    try {
      const r = await fetch(api + "/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": key,
        },
        body: JSON.stringify({ question: q, include_timings: true }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
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
      state.testMessages.push({
        role: "assistant",
        content: "Error: " + e.message,
      });
      renderTestMessages();
      toast(e.message, false);
    } finally {
      $("btnTestSend").disabled = false;
    }
  };

  // ── Users ──
  function renderUsers() {
    $("aUser").innerHTML = state.users
      .map((u) => `<option value="${u.id}">${esc(u.full_name)} (${esc(u.email)})</option>`)
      .join("");
    $("aTenant").innerHTML = state.tenants
      .map((t) => `<option value="${t.id}">${esc(t.name)}</option>`)
      .join("");
    $("usersBody").innerHTML = state.users
      .map(
        (u) => `<tr>
        <td>${esc(u.full_name)}</td>
        <td>${esc(u.email)}</td>
        <td>${esc(u.role)}</td>
        <td><span class="badge ${u.status === "active" ? "ok" : "err"}">${esc(
          u.status
        )}</span></td>
        <td>${
          u.status === "active"
            ? `<button class="btn sm danger" data-dis="${u.id}">Disable</button>`
            : `<button class="btn sm" data-en="${u.id}">Enable</button>`
        }</td>
      </tr>`
      )
      .join("");
    $("usersBody").querySelectorAll("[data-dis]").forEach((b) => {
      b.onclick = async () => {
        try {
          await req(`/admin/users/${b.dataset.dis}`, {
            method: "PATCH",
            headers: headers(true),
            body: JSON.stringify({ status: "disabled" }),
          });
          toast("User disabled");
          refresh();
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
    $("usersBody").querySelectorAll("[data-en]").forEach((b) => {
      b.onclick = async () => {
        try {
          await req(`/admin/users/${b.dataset.en}`, {
            method: "PATCH",
            headers: headers(true),
            body: JSON.stringify({ status: "active" }),
          });
          toast("User enabled");
          refresh();
        } catch (e) {
          toast(e.message, false);
        }
      };
    });
  }

  $("btnCreateUser").onclick = async () => {
    try {
      await req("/admin/users", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          email: $("uEmail").value,
          full_name: $("uName").value,
          role: $("uRole").value,
          password: $("uPass").value || null,
        }),
      });
      toast("User created");
      refresh();
    } catch (e) {
      toast(e.message, false);
    }
  };

  $("btnAssign").onclick = async () => {
    try {
      await req("/admin/users/assign", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          user_id: $("aUser").value,
          tenant_id: $("aTenant").value,
          role: $("aRole").value,
        }),
      });
      toast("Assigned to company");
    } catch (e) {
      toast(e.message, false);
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
            `<button type="button" class="model-chip ${
              x.is_default ? "default" : ""
            }" data-mid="${esc(x.model_id)}">${esc(x.label)}${
              x.is_default ? " · default" : ""
            }</button>`
        )
        .join("");
      $("modelChips").querySelectorAll("[data-mid]").forEach((b) => {
        b.onclick = () => {
          $("sysModel").value = b.dataset.mid;
        };
      });
    } catch {
      /* */
    }
  }

  $("btnSaveModel").onclick = async () => {
    try {
      await req("/admin/models/default", {
        method: "PUT",
        headers: headers(true),
        body: JSON.stringify({ model_id: $("sysModel").value }),
      });
      toast("Default model saved");
      renderSystem();
    } catch (e) {
      toast(e.message, false);
    }
  };

  // ── Add company modal ──
  function openAddModal() {
    $("modalAdd").classList.remove("hidden");
    $("mSecret").classList.add("hidden");
    $("mName").value = "";
  }
  $("btnAddCompany").onclick = openAddModal;
  $("btnAddCompany2").onclick = openAddModal;
  $("mCancel").onclick = () => $("modalAdd").classList.add("hidden");
  $("mSave").onclick = async () => {
    try {
      const d = await req("/admin/onboard", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          company_name: $("mName").value,
          key_name: $("mKeyName").value || "production",
          default_model: $("mModel").value || null,
        }),
      });
      state.testKeys[d.tenant.id] = d.api_key;
      sessionStorage.setItem("rag_test_keys", JSON.stringify(state.testKeys));
      const box = $("mSecret");
      box.classList.remove("hidden");
      box.innerHTML = `<strong>Company created · copy key now</strong><br/>
        ${esc(d.tenant.name)} · <code>${esc(d.tenant.id)}</code><br/><br/>
        <strong>API key</strong><br/>${esc(d.api_key)}<br/>
        <button type="button" class="btn sm" id="mCopyKey" style="margin-top:8px">Copy key</button>
        <button type="button" class="btn sm primary" id="mOpenCfg" style="margin-top:8px">Configure company</button>`;
      $("mCopyKey").onclick = () => copyText("API key", d.api_key);
      $("mOpenCfg").onclick = () => {
        $("modalAdd").classList.add("hidden");
        openDesk(d.tenant.id);
      };
      toast("Company onboarded");
      await refresh();
    } catch (e) {
      toast(e.message, false);
    }
  };

  $("companySearch").oninput = renderCompanies;
  $("btnRefresh").onclick = refresh;

  refresh();
})();
