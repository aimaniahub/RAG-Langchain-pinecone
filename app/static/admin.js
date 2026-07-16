(() => {
  const $ = (id) => document.getElementById(id);
  const apiBase = "/api/v1";
  let chartStages;

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

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function refreshAll() {
    try {
      const dash = await api("/admin/dashboard", { headers: headers(false) });
      const u = dash.usage || {};
      $("sQueries").textContent = u.query_count ?? 0;
      $("sIngests").textContent = u.ingest_count ?? 0;
      $("sDocs").textContent = `${u.documents_ready ?? 0}/${u.documents_total ?? 0}`;
      $("sAvg").textContent =
        u.avg_latency_ms != null ? `${u.avg_latency_ms}ms` : "—";
      $("sSessions").textContent = u.chat_sessions ?? 0;
      $("sMessages").textContent = u.chat_messages ?? 0;
      $("sFailed").textContent = u.documents_failed ?? 0;
      const lags = u.lag_stage_counts || {};
      $("sLag").textContent =
        Object.keys(lags).sort((a, b) => lags[b] - lags[a])[0] || "—";

      $("integrations").textContent = JSON.stringify(dash.integrations, null, 2);
      const integ = dash.integrations || {};
      const ok = integ.database && integ.openrouter && integ.pinecone;
      $("statusPill").className = ok ? "pill pill-ok" : "pill pill-warn";
      $("statusPill").textContent = ok ? "ready" : "check integrations";

      const live = u.live_metrics?.avg_ms || {};
      ensureChart();
      if (chartStages) {
        const labels = ["embed", "retrieve", "rerank", "context", "llm", "total"];
        chartStages.data.datasets[0].data = labels.map((k) => live[k] ?? 0);
        chartStages.update();
      }
    } catch (e) {
      $("statusPill").className = "pill pill-err";
      $("statusPill").textContent = e.message.slice(0, 40);
    }

    try {
      const docs = await api("/admin/documents", { headers: headers(false) });
      const tbody = $("docsTable").querySelector("tbody");
      tbody.innerHTML = (docs.items || [])
        .map(
          (d) => `<tr>
          <td>${esc(d.filename)}</td>
          <td>${esc(d.status)}</td>
          <td>${d.chunk_count}</td>
          <td>${d.vector_count}</td>
          <td>${d.size_bytes}</td>
          <td>${esc(d.storage_backend)}</td>
          <td>
            <button type="button" class="btn ghost" data-re="${d.id}">Reprocess</button>
            <button type="button" class="btn ghost" data-del="${d.id}">Delete</button>
          </td>
        </tr>`
        )
        .join("");
      tbody.querySelectorAll("[data-re]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            await api(`/admin/documents/${btn.dataset.re}/reprocess`, {
              method: "POST",
              headers: headers(false),
            });
            refreshAll();
          } catch (e) {
            alert(e.message);
          }
        });
      });
      tbody.querySelectorAll("[data-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!confirm("Delete document?")) return;
          try {
            await api(`/admin/documents/${btn.dataset.del}`, {
              method: "DELETE",
              headers: headers(false),
            });
            refreshAll();
          } catch (e) {
            alert(e.message);
          }
        });
      });
    } catch (e) {
      /* ignore if unauthorized */
    }

    try {
      const ev = await api("/admin/usage/events?limit=40", {
        headers: headers(false),
      });
      $("eventsTable").querySelector("tbody").innerHTML = (ev.items || [])
        .map(
          (e) => `<tr>
          <td>${esc(e.created_at || "")}</td>
          <td>${esc(e.event_type)}</td>
          <td>${esc(e.user_name)}</td>
          <td>${e.latency_ms ?? "—"}</td>
          <td class="lag">${esc(e.lag_stage)}</td>
          <td>${esc(e.cache_hit)}</td>
          <td>${esc(e.model)}</td>
        </tr>`
        )
        .join("");
    } catch {
      /* */
    }
  }

  function ensureChart() {
    if (typeof Chart === "undefined" || chartStages) return;
    chartStages = new Chart($("chartStages"), {
      type: "bar",
      data: {
        labels: ["embed", "retrieve", "rerank", "context", "llm", "total"],
        datasets: [
          {
            data: [0, 0, 0, 0, 0, 0],
            backgroundColor: [
              "#7aa2ff",
              "#3ecf8e",
              "#f0b429",
              "#c084fc",
              "#ff6b7a",
              "#94a3b8",
            ],
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { color: "#9aabcb" }, grid: { color: "#2a3655" } },
          x: { ticks: { color: "#9aabcb" }, grid: { display: false } },
        },
      },
    });
  }

  $("btnUpload").addEventListener("click", async () => {
    const f = $("file").files?.[0];
    if (!f) {
      $("uploadOut").className = "code-block error";
      $("uploadOut").textContent = "Choose a file";
      return;
    }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("namespace", $("namespace").value.trim() || "default");
    fd.append("async_process", $("asyncProcess").checked ? "true" : "false");
    $("uploadOut").className = "code-block loading";
    $("uploadOut").textContent = "Uploading & embedding";
    try {
      const res = await fetch(`${apiBase}/admin/documents`, {
        method: "POST",
        headers: headers(false),
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.message || "upload failed");
      $("uploadOut").className = "code-block ok";
      $("uploadOut").textContent = JSON.stringify(data, null, 2);
      refreshAll();
    } catch (e) {
      $("uploadOut").className = "code-block error";
      $("uploadOut").textContent = e.message;
    }
  });

  $("btnRefresh").addEventListener("click", refreshAll);
  refreshAll();
})();
