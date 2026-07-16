# Plan: Enterprise Admin UX Rebuild  
## Companies hub · Postgres-backed actions · Test API · No raw JSON

> **Status:** Planning only — implement after approval  
> **Do not push to git until you say**  
> **Goal:** Fully functional, consistent Admin UI where every button hits Postgres + real APIs; clear tenant lifecycle; Test API for live RAG checks

---

## 1. Problems (what you reported)

| Issue | Reality today |
|-------|----------------|
| Inconsistent UI / buttons | Mix of working forms and dead or unclear actions |
| Unnecessary / non-functional sections | Raw `<pre>` JSON dumps; old panels still hanging around |
| Tenant process unclear | Onboard + tenants + keys split without a single “company desk” |
| No easy copy of base URL / endpoints / keys | Key shown once in a box; no structured “integration card” |
| Doubt some parts are static | Some panels only re-render JSON; not always wired to list/detail APIs |
| JSON-heavy UI | Operators should see tables, badges, modals — not raw API payloads |
| Missing Test API | No place to pick a company and chat against *their* key/namespace |
| Companies list too flat | Need list → **Configure** drawer/page for models, keys, docs, usage |

---

## 2. Product principles (non-negotiable)

1. **API platform first** — Admin is for *operators*; clients use keys + HTTP.  
2. **Postgres is source of truth** — tenants, users, memberships, keys, documents, usage.  
3. **Every button = real HTTP call** — GET list, POST create, PATCH update, DELETE remove. No fake/static data.  
4. **No raw JSON in operator UI** — format as cards, tables, badges, forms. (JSON only in optional “Debug” collapsible, default hidden.)  
5. **One clear company lifecycle** — create company → issue key → upload docs → test → hand off integration card.  
6. **Copy-friendly integration info** — base URL, endpoints, headers, sample curl, with **Copy** buttons.

---

## 3. Target Admin information architecture

```
/admin
├── Home              Setup checklist (live from GET /admin/setup) + next action
├── Companies         List of tenants  →  [Configure] opens Company Desk
├── Test API          Pick company → temporary chat against that tenant’s RAG
├── Users             Platform users + assign to companies
└── System            Integrations health, embedding/LLM defaults (not JSON wall)
```

**Removed / demoted from main nav**

- Separate shallow “Keys / Docs / Models / Usage” top-level tabs (moved *inside* Company Desk)  
- “Quick Onboard” as a lonely form → becomes **primary CTA on Companies** (“Add company”)  
- Raw “partner endpoints” pre blocks → **Integration card** component with copy

---

## 4. Companies experience (core redesign)

### 4.1 Companies list page

| UI element | Behavior |
|------------|----------|
| Search | Filter by name/slug (client-side first; server filter later if needed) |
| Table/cards | Name, status badge, namespace, model, docs count, keys count, last activity |
| **Add company** | Modal: name, optional slug, default model → `POST /admin/onboard` *or* create tenant then key in 2-step wizard |
| **Configure** | Opens Company Desk (route or full-width drawer) for that `tenant_id` |
| **Disable / Enable** | `PATCH /admin/tenants/{id}` status |
| Empty state | “No companies yet” + big **Add company** + 3-step explainer |

### 4.2 Company Desk (config window)

Single place for one tenant. Tabs **inside** the desk:

| Tab | Content | APIs |
|-----|---------|------|
| **Overview** | Status, namespace, model, rate limit, notes, **Integration card** | `GET /admin/tenants/{id}` |
| **API keys** | List keys (prefix, scopes, status, last used); Issue / Revoke / Rotate; **Copy base URL + sample** | keys CRUD |
| **Documents** | List docs for tenant; Upload; Reprocess; Delete; status badges | documents APIs |
| **Models** | Select LLM for this tenant; save override | `PATCH .../models` |
| **Users** | Members of this tenant; assign/remove | users/assign + members list |
| **Usage** | Query counts, recent events for this tenant only | usage filtered by tenant_id |
| **Danger** | Disable tenant, confirm revoke all keys | PATCH / DELETE patterns |

### 4.3 Integration card (always visible on Overview)

Shown after company exists (and after key issue):

| Field | Source | Copy? |
|-------|--------|-------|
| Base URL | `window.location.origin` (or `PUBLIC_BASE_URL` env) | Yes |
| Auth header | `X-API-Key: <value>` — only if just issued; else “issue a key” | Yes when available |
| Query endpoint | `POST {base}/api/v1/query` | Yes |
| Ingest file | `POST {base}/api/v1/ingest/file` | Yes |
| Documents | `GET {base}/api/v1/documents` | Yes |
| Namespace | tenant.pinecone_namespace (read-only) | Yes |
| Sample curl | Generated string | Yes |

**Important:** Full API secret is only copyable **at issue/rotate time**. Later, card shows `rag_live_xxxx…` prefix only + “Rotate to get a new secret”.

---

## 5. Test API tab (new)

Purpose: **prove** the pipeline works for a selected company without leaving Admin.

| Control | Behavior |
|---------|----------|
| Company selector | Dropdown: company name (from `GET /admin/tenants`) — shows name, not only UUID |
| Active key mode | Option A: use **last issued key in session** (memory). Option B: paste temporary test key. Option C: “Use platform admin + force tenant namespace” only for operators if we add an admin-test endpoint (prefer A/B for real client path) |
| Chat panel | Message list + input; each send = `POST /api/v1/query` with that key |
| Meta under answer | Latency, lag stage, model, source count (formatted chips, not JSON) |
| Sources accordion | Expandable text snippets |
| Errors | Human toast/banner (401/403/502), not raw dumps |

**Recommended implementation for correctness**

- Prefer testing with a **real tenant API key** (same path clients use).  
- Flow: select company → if no session key, button **“Issue temporary test key”** (`POST .../keys` with name `admin-test`) → store in browser sessionStorage for that tenant → chat.  
- Optional: auto-revoke test keys older than 24h later (out of v1).

This guarantees Test API is **not static** and hits Postgres + Pinecone + OpenRouter.

---

## 6. Postgres connectivity (production confidence)

### 6.1 What must live in Postgres

| Entity | Create | Read | Update | Delete/Revoke |
|--------|--------|------|--------|---------------|
| Tenant | ✓ | ✓ | ✓ | soft disable |
| User | ✓ | ✓ | status/role | soft disable |
| TenantMember | ✓ | ✓ | role | remove membership |
| ApiKey | ✓ | ✓ (no secret) | — | revoke/rotate |
| Document | ✓ | ✓ | reprocess | delete row (+ storage) |
| ModelCatalog | seed + default | ✓ | enable/default | — |
| UsageEvent | write on query/ingest | ✓ | — | — |

### 6.2 Production wiring checklist

| Item | Action |
|------|--------|
| `DATABASE_URL` | Railway Postgres plugin → app service variable |
| `AUTO_MIGRATE=true` | `create_all` / Alembic on boot creates missing tables |
| Schema drift | Ship Alembic revision for `users`, `tenant_members`, extra columns if DB already exists |
| Health | `GET /admin/setup` shows `integrations.database` + scheme `postgresql` |
| Verify | After deploy: onboard company → row appears in Postgres `tenants` / `api_keys` |

### 6.3 Guarantee “not static”

| UI section | Proof of live data |
|------------|-------------------|
| Checklist | Counts from SQL aggregates |
| Companies list | `GET /admin/tenants` |
| Configure desk | `GET /admin/tenants/{id}` |
| Keys | Issue → DB hash; list from DB; revoke updates status |
| Docs | Upload → DB document + storage + Pinecone |
| Users | Create/assign → `users` / `tenant_members` |
| Usage | `usage_events` rows |
| Test API | Live `POST /query` |

---

## 7. UI formatting rules (kill raw JSON)

| Instead of JSON | Use |
|-----------------|-----|
| Integration flags | Green/red status pills (DB, Pinecone, OpenRouter, Storage) |
| Setup steps | Checklist with ✓ / next highlight |
| Tenants / keys / docs | Tables + badges (`active`, `ready`, `failed`, `revoked`) |
| Errors | Toast or inline alert with message only |
| Models | Radio/select list + “Default” badge |
| Usage | Stat cards + simple table of recent events |
| Debug | Optional `<details>Debug payload</details>` (off by default) |

---

## 8. CRUD matrix (every action must work)

### Companies
| Action | Method | Endpoint |
|--------|--------|----------|
| List | GET | `/api/v1/admin/tenants` |
| Create / onboard | POST | `/api/v1/admin/onboard` or `/admin/tenants` |
| Get desk | GET | `/api/v1/admin/tenants/{id}` |
| Update config | PATCH | `/api/v1/admin/tenants/{id}` |
| Set model | PATCH | `/api/v1/admin/tenants/{id}/models` |
| Disable | PATCH | status=`disabled` |

### API keys
| Action | Method | Endpoint |
|--------|--------|----------|
| List | GET | `/api/v1/admin/keys?tenant_id=` |
| Issue | POST | `/api/v1/admin/tenants/{id}/keys` |
| Revoke | POST | `/api/v1/admin/keys/{id}/revoke` |
| Rotate | POST | `/api/v1/admin/keys/{id}/rotate` |

### Documents
| Action | Method | Endpoint |
|--------|--------|----------|
| List by tenant | GET | `/api/v1/admin/documents?tenant_id=` |
| Upload | POST | `/api/v1/admin/tenants/{id}/documents` |
| Reprocess | POST | `/api/v1/admin/documents/{id}/reprocess` |
| Delete | DELETE | `/api/v1/admin/documents/{id}` |

### Users
| Action | Method | Endpoint |
|--------|--------|----------|
| List | GET | `/api/v1/admin/users` |
| Create | POST | `/api/v1/admin/users` |
| Assign | POST | `/api/v1/admin/users/assign` |
| Members | GET | `/api/v1/admin/tenants/{id}/members` |

### Test API
| Action | Method | Endpoint |
|--------|--------|----------|
| Query as client | POST | `/api/v1/query` with tenant key |

All success/error paths update UI state (reload list or optimistic patch + confirm from server).

---

## 9. Clear company process (operator SOP)

```
1. Home → confirm DB + OpenRouter + Pinecone green
2. Companies → Add company (or Quick Onboard)
3. Configure → API Keys → Issue key → Copy key + base URL
4. Configure → Documents → Upload handbook
5. Wait status = ready
6. Test API → select company → ask question → verify answer/sources
7. Share Integration card with client company
8. Usage tab/desk → monitor queries
```

UI must literally guide this with **Next step** banner (already started via setup API; keep it accurate and linked to the right tab).

---

## 10. Frontend structure (implementation plan)

### 10.1 Single SPA-style admin (rewrite)

Files (replace confusing multi-files):

| File | Role |
|------|------|
| `admin_console.html` | Shell: nav, company desk modal/drawer, test chat |
| `admin_console.css` | Layout, tables, modals, chips (no new framework) |
| `admin_console.js` | State, fetch helpers, renderers, copy buttons |

Remove operator dependency on: old `platform.html/js`, cluttered `admin.html/js` (delete or stop linking).

### 10.2 Client module pattern in JS

```
state = { tenants, selectedTenantId, deskTab, testMessages, lastIssuedKeys }
api.get/post/patch/delete
renderCompanies()
openCompanyDesk(id)
renderDeskOverview() / Keys / Docs / Models / Users / Usage
renderTestApi()
copyText(label, value)
toast(ok|error)
```

### 10.3 Company desk UI pattern

- Right-side **drawer** (desktop) or full page section (mobile)  
- Header: company name + status + Close  
- Horizontal sub-tabs  
- Sticky Integration card on Overview  

---

## 11. Backend gaps to close while doing UI

| Gap | Work |
|-----|------|
| Usage filter by tenant | `GET /admin/usage/events?tenant_id=` + summary by tenant |
| Public base URL | Config `PUBLIC_BASE_URL` for Railway public domain in Integration card |
| Membership remove | `DELETE /admin/tenants/{id}/members/{membership_id}` |
| User disable | `PATCH /admin/users/{id}` status |
| Doc list always scoped | Already supports `tenant_id` query — UI must always pass it in desk |
| Alembic for new tables | Ensure production Postgres gets `users`, `tenant_members` if not only `create_all` |
| Error shape | Consistent `{status, message}` for UI toasts |

---

## 12. Implementation phases (ordered)

### Phase 1 — Foundation cleanup (½–1 day)
- Wire Admin only to `admin_console.*`  
- Remove/hide dead admin pages from routes  
- Add `PUBLIC_BASE_URL`  
- Ensure lifespan seeds models + bootstrap user on Postgres  
- Confirm CRUD endpoints return structured JSON (for UI mapping, not for display)

### Phase 2 — Companies list + Company Desk (core)
- Redesign Companies list  
- Implement Configure drawer with Overview + Integration card (copy buttons)  
- Keys / Docs / Models / Users / Usage tabs all live-fetched for that tenant  
- Disable/enable tenant  

### Phase 3 — Test API tab
- Company dropdown (name visible)  
- Issue/store test key per tenant  
- Chat UI calling real `/query`  
- Formatted answer + sources + latency chips  

### Phase 4 — Polish & correctness pass
- Toasts, loading spinners, empty states  
- Confirm every Delete/Revoke refreshes list from server  
- Postgres production checklist document in README  
- Manual QA script (below)

### Phase 5 — (Optional) remove remaining JSON entirely
- System health as pills only  
- Usage as charts (can reuse Chart.js lightly)

---

## 13. Manual QA script (definition of done)

| # | Test | Pass criteria |
|---|------|----------------|
| 1 | Open `/admin` with admin key | Setup checklist loads from API |
| 2 | Onboard “Acme” | Row in Postgres `tenants` + `api_keys` |
| 3 | Copy base URL + key from Integration card | Clipboard works; key only at issue time |
| 4 | Upload PDF for Acme | `documents` row status `ready`, vectors > 0 |
| 5 | Test API → select Acme → ask | Answer returns; `usage_events` row with tenant_id |
| 6 | Revoke key | Status `revoked`; query with old key → 401 |
| 7 | Delete document | Gone from list; DB row deleted |
| 8 | Assign user to Acme | `tenant_members` row exists |
| 9 | Change tenant model | `tenants.default_model` updated; next query uses it |
| 10 | Disable tenant | New queries with that key fail or tenant blocked |
| 11 | Railway Postgres | `integrations.database_url_scheme` = `postgresql` |

---

## 14. What we will **not** do in this rebuild

- Rebuild client chat product as primary UI  
- Show full API secrets after leave-page (security)  
- Fake demo charts without DB data  
- Multiple competing admin HTML apps  

---

## 15. Approval gate

| Decision | Default |
|----------|---------|
| Company Desk = drawer (not separate URL)? | **Drawer** |
| Test API uses real tenant key? | **Yes** |
| Onboard creates key automatically? | **Yes** |
| Kill all raw JSON panels? | **Yes** (debug optional) |
| Implement Phases 1–4 now after approval? | Wait for your **build** |

**Approved by:** _______________ **Date:** _______________

---

## 16. Summary

| Area | Plan outcome |
|------|----------------|
| Companies | List + **Configure** desk (models, keys, docs, users, usage) |
| Process | Clear 7-step setup + Integration card with **copy** |
| Postgres | All entities CRUD; production `DATABASE_URL` required |
| UI | Formatted enterprise admin; no JSON walls |
| Test API | Select company by name → live chat test |
| Quality | Full delete/fetch/post matrix verified |

---

*End of plan. No implementation until you approve.*
```
