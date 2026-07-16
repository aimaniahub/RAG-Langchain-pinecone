(() => {
  const $ = (id) => document.getElementById(id);
  const api = "/api/v1";
  const keyEl = $("apiKey");
  keyEl.value = localStorage.getItem("rag_api_key") || "dev-admin-key";
  keyEl.onchange = () => localStorage.setItem("rag_api_key", keyEl.value.trim());

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
    if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
    return d;
  }

  document.querySelectorAll(".nav button[data-panel]").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".nav button[data-panel]").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("panel-" + btn.dataset.panel).classList.add("active");
    };
  });

  async function refresh() {
    try {
      $("sysHealth").textContent = JSON.stringify(
        await req("/admin/system/health", { headers: headers(false) }),
        null,
        2
      );
      $("sysConfig").textContent = JSON.stringify(
        await req("/admin/system/config", { headers: headers(false) }),
        null,
        2
      );
    } catch (e) {
      $("sysHealth").textContent = e.message;
    }

    try {
      const t = await req("/admin/tenants", { headers: headers(false) });
      $("tenantsTable").querySelector("tbody").innerHTML = (t.items || [])
        .map(
          (x) =>
            `<tr><td>${esc(x.name)}</td><td>${esc(x.slug)}</td><td>${esc(
              x.pinecone_namespace
            )}</td><td>${esc(x.default_model)}</td><td>${esc(x.status)}</td><td><code>${esc(
              x.id
            )}</code></td></tr>`
        )
        .join("");
    } catch (e) {
      /* */
    }

    try {
      const k = await req("/admin/keys", { headers: headers(false) });
      $("keysTable").querySelector("tbody").innerHTML = (k.items || [])
        .map(
          (x) =>
            `<tr><td>${esc(x.name)}</td><td>${esc(x.key_prefix)}</td><td>${esc(
              x.role
            )}</td><td>${esc(x.tenant_id || "—")}</td><td>${esc(
              (x.scopes || []).join(",")
            )}</td><td>${esc(x.status)}</td><td>${
              x.status === "active"
                ? `<button class="btn ghost" data-rev="${x.id}">Revoke</button>`
                : ""
            }</td></tr>`
        )
        .join("");
      $("keysTable").querySelectorAll("[data-rev]").forEach((b) => {
        b.onclick = async () => {
          if (!confirm("Revoke key?")) return;
          await req(`/admin/keys/${b.dataset.rev}/revoke`, {
            method: "POST",
            headers: headers(false),
          });
          refresh();
        };
      });
    } catch (e) {
      /* */
    }

    try {
      $("modelsOut").textContent = JSON.stringify(
        await req("/admin/models", { headers: headers(false) }),
        null,
        2
      );
    } catch (e) {
      $("modelsOut").textContent = e.message;
    }

    try {
      const d = await req("/admin/documents", { headers: headers(false) });
      $("docsTable").querySelector("tbody").innerHTML = (d.items || [])
        .map(
          (x) =>
            `<tr><td>${esc(x.filename)}</td><td>${esc(x.tenant_id || "—")}</td><td>${esc(
              x.status
            )}</td><td>${x.vector_count}</td><td>${esc(x.namespace)}</td></tr>`
        )
        .join("");
    } catch (e) {
      /* */
    }

    try {
      $("usageOut").textContent = JSON.stringify(
        await req("/admin/usage/summary", { headers: headers(false) }),
        null,
        2
      );
    } catch (e) {
      $("usageOut").textContent = e.message;
    }
  }

  $("btnCreateTenant").onclick = async () => {
    try {
      const d = await req("/admin/tenants", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          name: $("tName").value,
          slug: $("tSlug").value || null,
          default_model: $("tModel").value || null,
        }),
      });
      alert("Created tenant " + d.tenant.id);
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnCreateKey").onclick = async () => {
    try {
      const scopes = $("kScopes").value.split(",").map((s) => s.trim()).filter(Boolean);
      const d = await req(`/admin/tenants/${$("kTenant").value}/keys`, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ name: $("kName").value || "prod", scopes }),
      });
      $("keyOnce").classList.remove("hidden");
      $("keyOnce").textContent =
        "COPY NOW (shown once):\n" + d.api_key + "\n\n" + d.warning;
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnCreatePlatformKey").onclick = async () => {
    try {
      const d = await req("/admin/keys/platform", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ name: $("kName").value || "platform" }),
      });
      $("keyOnce").classList.remove("hidden");
      $("keyOnce").textContent = "PLATFORM KEY (copy once):\n" + d.api_key;
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnSetDefault").onclick = async () => {
    try {
      await req("/admin/models/default", {
        method: "PUT",
        headers: headers(true),
        body: JSON.stringify({ model_id: $("mDefault").value }),
      });
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnTenantModel").onclick = async () => {
    try {
      await req(`/admin/tenants/${$("mTenant").value}/models`, {
        method: "PATCH",
        headers: headers(true),
        body: JSON.stringify({ model_id: $("mTenantModel").value }),
      });
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnUploadDoc").onclick = async () => {
    const f = $("dFile").files?.[0];
    const tid = $("dTenant").value.trim();
    if (!f || !tid) return alert("Tenant ID + file required");
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch(api + `/admin/tenants/${tid}/documents`, {
        method: "POST",
        headers: headers(false),
        body: fd,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || d.message || "fail");
      alert("Uploaded: " + d.document.status);
      refresh();
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnRefresh").onclick = refresh;

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  refresh();
})();
