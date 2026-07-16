# Plan: Multi-Company RAG API Platform  
## Backend-as-a-Service — API keys, endpoints, structured Admin

> **Status:** Planning only — implement after approval  
> **Product identity:** This project is a **RAG API backend**, not a chat product.  
> **Customers:** Other companies integrate via **API keys + HTTP endpoints**.  
> **Operators:** Platform admins manage keys, models, corpora, usage via **Admin API** (and optional thin admin console later).

---

## 1. Goal (your intent, restated)

| You want | You do **not** want |
|----------|---------------------|
| Clean **REST/JSON API** for RAG (query, ingest, health) | Chat UI as the “product” |
| **API keys** for each client company / app | App that only works in its own browser UI |
| **Admin** to issue keys, set models, monitor usage | Scattered env-only secrets with no control plane |
| Platform **serves other systems** | End-user “company chatbot website” as primary surface |
| OpenAPI as the contract | Frontend-first experience |

**One-line product:**  
> *Hosted multi-tenant RAG engine: clients call endpoints with an API key; admins configure tenants, keys, models, and knowledge.*

---

## 2. Current gap vs goal

| Area | Today | Target |
|------|--------|--------|
| Product surface | `/chat`, `/admin` HTML, `/ui` | **API-first**; UIs optional/internal only |
| Auth | Env API keys (`API_KEY_ADMIN` / `API_KEY_USER`) | **DB-managed keys** per tenant + scopes |
| Tenancy | Single namespace-ish | **Tenant (company)** isolation: keys, docs, Pinecone namespace, usage |
| Models | Global `.env` OpenRouter model | **Per-tenant model config** (with platform defaults) |
| Admin | Loose dashboard + upload | **Structured admin modules**: tenants, keys, models, corpus, usage, system |
| Client DX | Mixed routes | Versioned **public API** + **admin API** with clear docs |
| Root `/` | Redirect to chat | Service info / OpenAPI link only |

---

## 3. Product model

### 3.1 Actors

| Actor | How they use the system |
|-------|-------------------------|
| **Platform super-admin** | Creates tenants, platform defaults, system health |
| **Tenant admin** (company ops) | Manage that company’s keys, uploads, model choice (if allowed) |
| **Client application** | Backend/frontend of another company; calls public RAG endpoints with **tenant API key** |

### 3.2 Core objects

```
Tenant (company)
  ├── settings: namespace, default model, rate limits, enabled flags
  ├── api_keys[]: key_id, hash, name, scopes, status, expires_at
  ├── documents[]: corpus for that tenant only
  └── usage_events[]: query/ingest billing & monitoring
```

### 3.3 Scopes (API key permissions)

| Scope | Allows |
|-------|--------|
| `query:read` | `POST /v1/query` (and stream if enabled) |
| `ingest:write` | `POST /v1/ingest`, file ingest |
| `docs:read` | List own documents (optional) |
| `admin:tenant` | Tenant-level admin APIs (keys under tenant, if delegated) |

Platform super-admin uses a **master admin key** (or separate bootstrap) for `/v1/admin/*`.

---

## 4. API surface (target contract)

Base URL: `https://<your-railway-host>`  
Prefix: **`/v1`** (stable public contract; migrate from `/api/v1` over time or alias both)

### 4.1 Public / client API (company integrations)

All require: `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| `GET` | `/v1/health` | none | Liveness (no secrets) |
| `GET` | `/v1/ready` | none or key | Dependency readiness |
| `POST` | `/v1/query` | `query:read` | RAG Q&A + sources + timings |
| `POST` | `/v1/query/stream` | `query:read` | Optional SSE (feature flag) |
| `POST` | `/v1/ingest` | `ingest:write` | Ingest texts |
| `POST` | `/v1/ingest/file` | `ingest:write` | Upload file → embed |
| `GET` | `/v1/documents` | `docs:read` | List **own** tenant docs |
| `GET` | `/v1/documents/{id}` | `docs:read` | Doc status |
| `DELETE` | `/v1/documents/{id}` | `ingest:write` | Delete doc (tenant-scoped) |

**Query body (example)**

```json
{
  "question": "What is the leave policy?",
  "top_k": 5,
  "include_timings": false
}
```

**Query response (example)**

```json
{
  "status": "ok",
  "answer": "...",
  "sources": [{ "content": "...", "score": 0.82, "metadata": {} }],
  "model": "openai/gpt-4o-mini",
  "request_id": "abc123",
  "usage": { "latency_ms": 1200, "context_tokens_est": 400 }
}
```

Client companies **never** need our chat UI — they build their own product on these endpoints.

### 4.2 Admin API (platform control plane)

Require **platform admin** key (or super-admin role).

Structured modules:

#### A. System
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/admin/system/health` | DB, S3, Pinecone, OpenRouter |
| `GET` | `/v1/admin/system/config` | Non-secret defaults (models list, limits) |

#### B. Tenants (companies you serve)
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/admin/tenants` | Create company/tenant |
| `GET` | `/v1/admin/tenants` | List tenants |
| `GET` | `/v1/admin/tenants/{id}` | Detail |
| `PATCH` | `/v1/admin/tenants/{id}` | Update name, status, limits, namespace |
| `POST` | `/v1/admin/tenants/{id}/disable` | Suspend API access |

#### C. API keys (core of “provide keys”)
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/admin/tenants/{id}/keys` | Create key (return **raw key once**) |
| `GET` | `/v1/admin/tenants/{id}/keys` | List keys (id, name, scopes, last_used — **no secret**) |
| `POST` | `/v1/admin/keys/{key_id}/revoke` | Revoke |
| `POST` | `/v1/admin/keys/{key_id}/rotate` | New secret, revoke old |

Create key response (only time plaintext is shown):

```json
{
  "key_id": "key_01H...",
  "api_key": "rag_live_xxxxx",
  "tenant_id": "...",
  "scopes": ["query:read", "ingest:write"],
  "warning": "Store this key now; it will not be shown again."
}
```

Store only **hash** (e.g. SHA-256 / bcrypt) in DB.

#### D. Models (platform + per-tenant)
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/admin/models` | Catalog of allowed OpenRouter model IDs |
| `PUT` | `/v1/admin/models/default` | Platform default chat model |
| `PATCH` | `/v1/admin/tenants/{id}/models` | Tenant override: chat model, temperature, top_k defaults |
| `GET` | `/v1/admin/models/embedding` | Embedding model info (usually global HF MiniLM) |

**Policy options (config flags):**
- `ALLOW_TENANT_MODEL_OVERRIDE=true|false`
- Allowed model allowlist (prevent arbitrary expensive models)

#### E. Corpus (tenant knowledge)
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/admin/tenants/{id}/documents` | All docs for tenant |
| `POST` | `/v1/admin/tenants/{id}/documents` | Admin upload on behalf of tenant |
| `POST` | `.../reprocess` | Rebuild vectors |
| `DELETE` | `.../{doc_id}` | Delete storage + mark vectors |

#### F. Usage & billing hooks
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/admin/usage/summary` | Global or by tenant |
| `GET` | `/v1/admin/tenants/{id}/usage` | Queries, latency, errors |
| `GET` | `/v1/admin/usage/timeseries` | Charts data |

---

## 5. Admin console (optional UI — control plane only)

**Not** a user chat app. If you keep any HTML:

| Section | Admin options |
|---------|----------------|
| **Overview** | System health, totals, errors |
| **Tenants** | Create/list/suspend companies |
| **Keys** | Issue, revoke, copy-once, scopes |
| **Models** | Default model, allowlist, tenant overrides |
| **Documents** | Upload/reprocess per tenant |
| **Usage** | Per-tenant queries, lag stages, rate-limit hits |

- Serve at `/admin` only (behind admin key or basic auth)  
- **Remove or disable** `/chat` and `/ui` as product surfaces (`UI_MODE=api_only|admin_only|full`)  
- Root `/` → JSON service descriptor + link to `/docs`

```json
{
  "service": "company-rag-api",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/v1/health",
  "message": "RAG API backend. Integrate with API keys."
}
```

---

## 6. Architecture (API platform)

```
Client company app                    Platform admin
       │                                     │
       │  X-API-Key: rag_live_xxx            │  Admin key
       ▼                                     ▼
┌──────────────────────────────────────────────────────┐
│                 RAG API Platform (Railway)             │
│  /v1/* public          /v1/admin/* control plane      │
│         │                         │                   │
│         ▼                         ▼                   │
│   AuthZ (key→tenant→scopes)   Tenants / Keys / Models │
│         │                         │                   │
│         ▼                         ▼                   │
│   Tenant RAG pipeline      Config + usage store       │
│   (namespace isolation)    (Postgres)                 │
│         │                                             │
│         ├── HF embeddings (or shared)                 │
│         ├── Pinecone namespace = tenant_id             │
│         └── OpenRouter model = tenant.model || default│
└──────────────────────────────────────────────────────┘
```

### Isolation rules

1. Every request resolves `api_key → tenant_id`.  
2. Pinecone **namespace** = `tenant.slug` or `tenant_id` (never share vectors across tenants).  
3. Documents and usage rows always carry `tenant_id`.  
4. Rate limits applied **per key** and/or **per tenant**.

---

## 7. Data model changes (Postgres)

### New / evolved tables

| Table | Purpose |
|-------|---------|
| `tenants` | id, name, slug, status, pinecone_namespace, default_model, rate_limit_rpm, created_at |
| `api_keys` | id, tenant_id, name, key_prefix, key_hash, scopes_json, status, last_used_at, expires_at |
| `tenant_settings` | optional JSON: temperature, top_k, max_context, features |
| `model_catalog` | id, provider, model_id, label, enabled, is_default |
| existing `documents` | **+ tenant_id** |
| existing `usage_events` | **+ tenant_id, api_key_id** |
| existing `chat_*` | **Optional / deprecate** for platform product (keep only if a tenant wants hosted chat later) |

### Key security

- Store `key_hash` only; show full key **once** at creation.  
- Prefix for support: `rag_live_ab12…` → store prefix `rag_live_ab12`.  
- Revoked keys fail auth immediately.

---

## 8. What to demote / remove from “product”

| Current | Decision |
|---------|----------|
| `/chat` UI | **Disable by default** (`ENABLE_CHAT_UI=false`) |
| `/ui` dev console | **Disable in production** or admin-only debug |
| `/` → chat redirect | **Replace** with API service JSON |
| Chat sessions as primary flow | Secondary; clients implement their own chat |

Keep chat **code** optional behind flag for demos — not the brand.

---

## 9. Implementation phases

### Phase A — Product reposition (fast, low risk)

1. Root `/` → service JSON (not chat).  
2. Flags: `ENABLE_CHAT_UI`, `ENABLE_DEV_UI`, `ENABLE_ADMIN_UI`.  
3. Production defaults: chat/dev off; OpenAPI on for partners or admin-only.  
4. README: “API platform for company integrations”.  
5. Document public vs admin routes clearly in OpenAPI tags.

**Exit:** Deployed service feels like an API, not a chatbot site.

### Phase B — Tenants + DB API keys

1. `tenants` + `api_keys` tables + migration.  
2. Auth middleware: resolve key from DB (fallback env keys for bootstrap).  
3. Admin endpoints: create tenant, create/revoke keys.  
4. Scope checks on query/ingest.  
5. Pinecone namespace from tenant.

**Exit:** You can issue a key to “Company X” and they can only hit their corpus.

### Phase C — Models control plane

1. `model_catalog` + platform default.  
2. Tenant model override.  
3. Admin list/update model settings.  
4. Query path uses tenant model when set.

**Exit:** Admin can change LLM per company without redeploy.

### Phase D — Structured Admin API + thin Admin UI

1. Group routes under `/v1/admin/{module}/...` as above.  
2. Rebuild admin UI as **operator console**: Tenants | Keys | Models | Docs | Usage | System.  
3. No end-user chat in admin.

**Exit:** Non-engineer operator can onboard a company (create tenant → create key → upload docs → share key).

### Phase E — Partner DX

1. OpenAPI examples + Postman collection.  
2. Rate limit headers (`X-RateLimit-*`).  
3. Webhooks optional (ingest completed).  
4. Usage export for billing.

---

## 10. Example partner integration flow

```
1. You (admin): POST /v1/admin/tenants { "name": "Acme Corp" }
2. You: POST /v1/admin/tenants/{id}/keys { "name": "acme-prod", "scopes": ["query:read","ingest:write"] }
   → receive rag_live_xxx (send securely to Acme once)
3. You or Acme: POST /v1/ingest/file with that key (handbook.pdf)
4. Acme app: POST /v1/query with same key { "question": "..." }
5. Acme renders answer in *their* product UI
```

Your platform never is Acme’s frontend.

---

## 11. Config surface (target)

```env
# Product mode
PRODUCT_MODE=api_platform          # api_platform | full_demo
ENABLE_CHAT_UI=false
ENABLE_DEV_UI=false
ENABLE_ADMIN_UI=true               # optional operator console
OPENAPI_PUBLIC=true                # or false + admin-only docs

# Bootstrap (first super-admin; then use DB keys)
BOOTSTRAP_ADMIN_KEY=...

# Defaults for new tenants
DEFAULT_OPENROUTER_MODEL=openai/gpt-4o-mini
ALLOW_TENANT_MODEL_OVERRIDE=true
DEFAULT_RATE_LIMIT_RPM=60
```

---

## 12. Success criteria

| Criterion | Done when |
|-----------|-----------|
| API-first | Root and README describe endpoints, not chat app |
| Multi-company | Two tenants, two keys, isolated namespaces |
| Key lifecycle | Create / list / revoke works; plaintext only once |
| Models | Admin sets default + per-tenant model |
| Partner ready | Third-party can integrate with only base URL + key + OpenAPI |
| Admin structured | Modules: System, Tenants, Keys, Models, Docs, Usage |

---

## 13. Out of scope (for this plan)

- White-label chat widgets for each company (their job)  
- Stripe billing UI (usage export is enough first)  
- Full SSO for admin (can add later; start with admin API key)  
- Marketplace of models beyond OpenRouter allowlist  

---

## 14. Recommended build order after approval

1. **Phase A** — API product mode flags + root JSON + disable chat as default  
2. **Phase B** — Tenants + DB API keys + namespace isolation  
3. **Phase C** — Models admin  
4. **Phase D** — Structured admin API + clean admin console  
5. **Phase E** — Partner docs / rate-limit headers  

---

## 15. Approval gate

| Question | Default if blank |
|----------|------------------|
| Chat UI off in production? | **Yes** |
| Multi-tenant via Pinecone namespace? | **Yes** |
| Admin = API + thin UI? | **Yes** |
| Clients get query + ingest only first? | **Yes** |
| Super-admin bootstrap via env key? | **Yes** |

**Approved by:** _______________ **Date:** _______________

---

## 16. Document control

| Field | Value |
|-------|--------|
| Document | `PLAN_API_PLATFORM.md` |
| Replaces product focus of | Chat-first Railway UI |
| Stack unchanged | FastAPI · HF · Pinecone · OpenRouter · Postgres · S3 |
| Next after approval | Implement Phase A → B |

---

*End of plan. Implementation starts only after you approve the phases above.*
```
