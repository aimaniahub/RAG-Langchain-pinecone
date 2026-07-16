(() => {
  const $ = (id) => document.getElementById(id);

  const apiBaseEl = $("apiBase");
  const apiKeyEl = $("apiKey");
  const namespaceEl = $("namespace");

  let chartStages, chartShare, chartRecent, chartCache;

  if (!apiKeyEl.value) {
    apiKeyEl.value = localStorage.getItem("rag_api_key") || "dev-admin-key";
  }
  apiKeyEl.addEventListener("change", () => {
    localStorage.setItem("rag_api_key", apiKeyEl.value.trim());
  });

  function base() {
    return (apiBaseEl.value || "/api/v1").replace(/\/$/, "");
  }

  function headers(json = true) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    const key = apiKeyEl.value.trim();
    if (key) h["X-API-Key"] = key;
    return h;
  }

  function pretty(obj) {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  }

  async function api(path, options = {}) {
    const res = await fetch(`${base()}${path}`, options);
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      const msg = data.detail || data.message || pretty(data);
      const err = new Error(typeof msg === "string" ? msg : pretty(msg));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ---- main tabs ----
  document.querySelectorAll(".main-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".main-tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".main-view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      $(`view-${btn.dataset.main}`).classList.add("active");
      if (btn.dataset.main === "monitor") refreshMetrics();
    });
  });

  // ---- work tabs ----
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  async function refreshHealth() {
    $("statusPill").className = "pill pill-muted";
    $("statusPill").textContent = "checking…";
    $("healthOut").className = "code-block";
    try {
      const [health, ready] = await Promise.all([api("/health"), api("/ready")]);
      $("healthOut").textContent = pretty({ health, ready });
      $("healthOut").classList.add("ok");
      const ok = ready.status === "ready";
      $("statusPill").className = ok ? "pill pill-ok" : "pill pill-warn";
      $("statusPill").textContent = ok
        ? `ready · phase ${ready.phase}`
        : `not ready · ${ready.detail || ""}`;
      $("footerPhase").textContent = `phase ${ready.phase || 3} · auth ${
        ready.auth_enabled ? "on" : "off"
      } · rerank ${ready.speed_features?.rerank ? "on" : "off"}`;
    } catch (e) {
      $("statusPill").className = "pill pill-err";
      $("statusPill").textContent = "offline";
      $("healthOut").className = "code-block error";
      $("healthOut").textContent = String(e.message || e);
    }
  }

  $("btnRefreshHealth").addEventListener("click", refreshHealth);

  $("btnIngestText").addEventListener("click", async () => {
    const text = $("ingestText").value.trim();
    if (!text) {
      $("ingestOut").className = "code-block error";
      $("ingestOut").textContent = "Enter document text.";
      return;
    }
    let metadata = {};
    try {
      metadata = JSON.parse($("ingestMeta").value || "{}");
    } catch {
      $("ingestOut").className = "code-block error";
      $("ingestOut").textContent = "Invalid metadata JSON.";
      return;
    }
    $("ingestOut").className = "code-block loading";
    $("ingestOut").textContent = "Ingesting";
    try {
      const data = await api("/ingest", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          texts: [text],
          metadata,
          namespace: namespaceEl.value.trim() || null,
        }),
      });
      $("ingestOut").className = "code-block ok";
      $("ingestOut").textContent = pretty(data);
    } catch (e) {
      $("ingestOut").className = "code-block error";
      $("ingestOut").textContent = `${e.status || ""} ${e.message}`.trim();
    }
  });

  $("btnIngestFile").addEventListener("click", async () => {
    const fileInput = $("ingestFile");
    if (!fileInput.files?.[0]) {
      $("ingestOut").className = "code-block error";
      $("ingestOut").textContent = "Choose a file.";
      return;
    }
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    const ns = namespaceEl.value.trim();
    if (ns) fd.append("namespace", ns);
    const meta = $("ingestFileMeta").value.trim();
    if (meta) fd.append("metadata_json", meta);
    $("ingestOut").className = "code-block loading";
    $("ingestOut").textContent = "Uploading";
    try {
      const data = await api("/ingest/file", {
        method: "POST",
        headers: headers(false),
        body: fd,
      });
      $("ingestOut").className = "code-block ok";
      $("ingestOut").textContent = pretty(data);
    } catch (e) {
      $("ingestOut").className = "code-block error";
      $("ingestOut").textContent = `${e.status || ""} ${e.message}`.trim();
    }
  });

  $("btnSampleQ").addEventListener("click", () => {
    $("question").value = "How many paid leave days do employees get per year?";
  });

  function renderTimingBar(timings) {
    const bar = $("timingBar");
    if (!timings) {
      bar.classList.add("hidden");
      return;
    }
    const stages = ["embed", "retrieve", "rerank", "context", "llm"];
    const total = stages.reduce((s, k) => s + (timings[k] || 0), 0) || 1;
    bar.innerHTML = stages
      .map((k) => {
        const ms = timings[k] || 0;
        const pct = Math.max(ms > 0 ? 4 : 0, (100 * ms) / total);
        return `<div class="timing-seg seg-${k}" style="width:${pct}%" title="${k}: ${ms}ms">${
          ms > 40 ? k + " " + ms : ms > 0 ? ms : ""
        }</div>`;
      })
      .join("");
    bar.classList.remove("hidden");
  }

  function showQueryResult(data) {
    $("answerBox").classList.remove("hidden");
    $("answerText").textContent = data.answer || "(empty)";
    const t = data.timings_ms || {};
    $("answerMeta").textContent = [
      `lag: ${data.lag_stage || "—"}`,
      `total: ${t.total ?? "—"}ms`,
      `embed: ${t.embed ?? "—"}`,
      `retrieve: ${t.retrieve ?? "—"}`,
      `rerank: ${t.rerank ?? "—"}`,
      `context: ${t.context ?? "—"}`,
      `llm: ${t.llm ?? "—"}`,
      `cache: ${data.cache_hit || "none"}`,
      `ctx~${data.context_tokens_est ?? "?"} tok`,
      `model: ${data.model || "—"}`,
    ].join(" · ");
    renderTimingBar(t);

    const sources = data.sources || [];
    if (sources.length) {
      $("sourcesBox").classList.remove("hidden");
      $("sourcesList").innerHTML = sources
        .map((s, i) => {
          const score =
            s.score == null
              ? ""
              : `<div class="source-score">#${i + 1} score ${Number(s.score).toFixed(4)}</div>`;
          return `<div class="source-item">${score}<div>${escapeHtml(
            s.content || ""
          )}</div></div>`;
        })
        .join("");
    } else {
      $("sourcesBox").classList.add("hidden");
    }
    $("queryOut").className = "code-block ok";
    $("queryOut").textContent = pretty(data);
  }

  $("btnQuery").addEventListener("click", async () => {
    const question = $("question").value.trim();
    if (!question) {
      $("queryOut").className = "code-block error";
      $("queryOut").textContent = "Enter a question.";
      return;
    }
    $("answerBox").classList.add("hidden");
    $("sourcesBox").classList.add("hidden");
    $("timingBar").classList.add("hidden");
    $("queryOut").className = "code-block loading";
    $("queryOut").textContent = "Querying (timings on)";
    $("btnQuery").disabled = true;
    try {
      const data = await api("/query", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          question,
          top_k: Number($("topK").value || 10),
          namespace: namespaceEl.value.trim() || null,
          include_timings: true,
        }),
      });
      showQueryResult(data);
    } catch (e) {
      $("queryOut").className = "code-block error";
      $("queryOut").textContent = `${e.status || ""} ${e.message}`.trim();
    } finally {
      $("btnQuery").disabled = false;
    }
  });

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  // ---- monitor ----
  function ensureCharts() {
    if (typeof Chart === "undefined") return;
    if (!chartStages) {
      chartStages = new Chart($("chartStages"), {
        type: "bar",
        data: {
          labels: ["embed", "retrieve", "rerank", "context", "llm", "total"],
          datasets: [
            {
              label: "avg ms",
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
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { color: "#9aabcb" }, grid: { color: "#2a3655" } },
            x: { ticks: { color: "#9aabcb" }, grid: { display: false } },
          },
        },
      });
    }
    if (!chartShare) {
      chartShare = new Chart($("chartShare"), {
        type: "doughnut",
        data: {
          labels: ["embed", "retrieve", "rerank", "context", "llm"],
          datasets: [
            {
              data: [0, 0, 0, 0, 0],
              backgroundColor: ["#7aa2ff", "#3ecf8e", "#f0b429", "#c084fc", "#ff6b7a"],
            },
          ],
        },
        options: {
          plugins: { legend: { labels: { color: "#9aabcb" } } },
        },
      });
    }
    if (!chartRecent) {
      chartRecent = new Chart($("chartRecent"), {
        type: "line",
        data: {
          labels: [],
          datasets: [
            {
              label: "total ms",
              data: [],
              borderColor: "#7aa2ff",
              tension: 0.25,
              fill: false,
            },
            {
              label: "llm ms",
              data: [],
              borderColor: "#ff6b7a",
              tension: 0.25,
              fill: false,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: { legend: { labels: { color: "#9aabcb" } } },
          scales: {
            y: { beginAtZero: true, ticks: { color: "#9aabcb" }, grid: { color: "#2a3655" } },
            x: { ticks: { color: "#9aabcb", maxRotation: 0 }, grid: { display: false } },
          },
        },
      });
    }
    if (!chartCache) {
      chartCache = new Chart($("chartCache"), {
        type: "bar",
        data: {
          labels: ["answer", "embed", "none"],
          datasets: [
            {
              label: "hits",
              data: [0, 0, 0],
              backgroundColor: ["#3ecf8e", "#7aa2ff", "#64748b"],
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
  }

  async function refreshMetrics() {
    ensureCharts();
    try {
      const [summary, recent] = await Promise.all([
        api("/metrics/summary"),
        api("/metrics/queries?limit=40"),
      ]);

      $("statCount").textContent = summary.count ?? 0;
      $("statAvg").textContent =
        summary.avg_ms?.total != null ? `${summary.avg_ms.total} ms` : "—";
      $("statP95").textContent =
        summary.p95_ms?.total != null ? `${summary.p95_ms.total} ms` : "—";

      const slow = summary.slowest_stage_counts || {};
      const lag =
        Object.keys(slow).sort((a, b) => (slow[b] || 0) - (slow[a] || 0))[0] || "—";
      $("statLag").textContent = lag;

      if (chartStages) {
        const labels = ["embed", "retrieve", "rerank", "context", "llm", "total"];
        chartStages.data.datasets[0].data = labels.map(
          (k) => summary.avg_ms?.[k] ?? 0
        );
        chartStages.update();
      }
      if (chartShare) {
        const share = summary.stage_share_pct || {};
        chartShare.data.datasets[0].data = [
          "embed",
          "retrieve",
          "rerank",
          "context",
          "llm",
        ].map((k) => share[k] ?? 0);
        chartShare.update();
      }
      if (chartCache) {
        const ch = summary.cache_hits || {};
        chartCache.data.datasets[0].data = [
          ch.answer || 0,
          ch.embed || 0,
          ch.none || 0,
        ];
        chartCache.update();
      }
      $("cacheStats").textContent = pretty(summary.cache_stats || {});

      const items = (recent.items || []).slice().reverse();
      if (chartRecent) {
        chartRecent.data.labels = items.map((_, i) => String(i + 1));
        chartRecent.data.datasets[0].data = items.map(
          (x) => x.timings_ms?.total ?? 0
        );
        chartRecent.data.datasets[1].data = items.map(
          (x) => x.timings_ms?.llm ?? 0
        );
        chartRecent.update();
      }

      const tbody = $("metricsTable").querySelector("tbody");
      tbody.innerHTML = (recent.items || [])
        .map((e) => {
          const t = e.timings_ms || {};
          const lagStage = (() => {
            const c = { ...t };
            delete c.total;
            const keys = Object.keys(c);
            if (!keys.length) return "—";
            return keys.sort((a, b) => (c[b] || 0) - (c[a] || 0))[0];
          })();
          return `<tr>
            <td>${escapeHtml(e.ts_iso || "")}</td>
            <td title="${escapeHtml(e.question_preview || "")}">${escapeHtml(
            (e.question_preview || "").slice(0, 36)
          )}</td>
            <td>${t.total ?? "—"}</td>
            <td>${t.embed ?? "—"}</td>
            <td>${t.retrieve ?? "—"}</td>
            <td>${t.rerank ?? "—"}</td>
            <td>${t.context ?? "—"}</td>
            <td>${t.llm ?? "—"}</td>
            <td class="lag">${escapeHtml(lagStage)}</td>
            <td>${escapeHtml(e.cache_hit || "")}</td>
            <td>${e.context_chars ?? "—"}</td>
          </tr>`;
        })
        .join("");
    } catch (e) {
      $("cacheStats").className = "code-block error";
      $("cacheStats").textContent = String(e.message || e);
    }
  }

  $("btnRefreshMetrics").addEventListener("click", refreshMetrics);
  $("btnClearMetrics").addEventListener("click", async () => {
    try {
      await api("/metrics", { method: "DELETE", headers: headers(false) });
      refreshMetrics();
    } catch (e) {
      alert(e.message || e);
    }
  });

  refreshHealth();
})();
