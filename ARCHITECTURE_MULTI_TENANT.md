# Multi-tenant store & retrieve architecture

## The problem you saw

Chat for **Core Tech** returned **QuizForge** content on follow-up (“what does it do”).

That is a **company isolation** failure: retrieval pulled chunks from the wrong company’s knowledge.

Typical causes:
1. Docs for two companies landed in the **same Pinecone namespace**
2. Chat used a **non-company key** (platform/admin/env key) → default namespace
3. Old vectors had **no tenant_id** metadata, so no second safety filter
4. Namespace on the document row drifted from the tenant’s current namespace

---

## Correct architecture (one company = one silo)

```
                    ┌─────────────────────────────┐
                    │     Platform Admin (/admin) │
                    │  manage companies, keys,    │
                    │  docs, RAG settings         │
                    └─────────────┬───────────────┘
                                  │
         create company           │ upload docs for company A only
         issue company API key    │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Postgres                                  │
│  tenants (company A, company B)                                   │
│    - pinecone_namespace  e.g. core_tech / quizforge               │
│    - system_prompt, top_k, limits (per company)                   │
│  api_keys → tenant_id  (each client key = one company)            │
│  documents → tenant_id + namespace + storage_key                  │
└──────────────────────────────────────────────────────────────────┘

Upload / embed for company A:
  File → S3: companies/{slug}/documents/{doc_id}/file.pdf
  Chunks → Pinecone index (shared) but namespace = A only
  Each vector metadata: tenant_id, tenant_slug, document_id, source, text

Query with company A key:
  Auth → resolve tenant_id + namespace from Postgres (never trust client body)
  Retrieve only: Pinecone namespace = A
  + metadata filter tenant_id = A  (defense in depth)
  LLM answers using only those chunks + company system prompt
```

### What lives where

| Data | Store | Isolation key |
|------|--------|----------------|
| Company row, settings, keys | Postgres | `tenants.id` |
| Original files | S3 / local | path `companies/{slug}/...` |
| Vectors (search) | Pinecone | **namespace = tenant.pinecone_namespace** |
| Vector metadata | Pinecone metadata | `tenant_id` (+ document_id) |
| Usage / audit | Postgres | `tenant_id` |

**Embeddings do not go to S3.**  
**S3 does not answer questions.**  
**Only Pinecone namespace + tenant filter decides which docs are searchable.**

---

## Hard rules (non-negotiable)

1. **One API key → one company** (`api_keys.tenant_id` required for client chat).
2. **Query never accepts client `namespace` override.** Server sets it from the key’s company.
3. **Upload from Admin always uses that company’s `pinecone_namespace`.**
4. **Every vector stores `tenant_id`.** Query filters by namespace **and** `tenant_id`.
5. **Platform admin key is for /admin only** — not for end-user chat `/query`.
6. **Never put two companies in namespace `default`.**

---

## Correct operator workflow

### Add company Core Tech
1. Admin → Add company “Core Tech”
2. Copy **company** API key (starts with `rag_live_…`)
3. Open company → RAG settings (prompt, top_k=3, …) → Save
4. Documents tab → upload **only Core Tech** PDFs/MD
5. Confirm message shows namespace e.g. `core_tech`

### Add company QuizForge
1. Separate company
2. **Different** API key
3. Upload **only QuizForge** docs
4. Different namespace e.g. `quizforge`

### Wire the Core Tech chat product
```
X-API-Key: <Core Tech company key only>
POST /api/v1/query
{ "question": "What is Core Tech?" }
```

Do **not** use `API_KEY_ADMIN` or a QuizForge key in the Core Tech chatbot.

---

## How retrieve works (happy path)

1. Request arrives with Core Tech key  
2. Hash key → `api_keys` → `tenant_id` = Core Tech  
3. Load tenant → `namespace = core_tech`, RAG settings  
4. Embed question  
5. Pinecone query: `namespace=core_tech` + `filter tenant_id=core-tech-uuid`  
6. top_k=3 best chunks **from Core Tech only**  
7. LLM + Core Tech system prompt → answer  

QuizForge vectors are **never scored** because they sit in another namespace.

---

## If isolation already broke (cleanup)

Old vectors may already sit in the wrong / shared namespace.

1. In Admin, for each company note: **slug** and **pinecone_namespace**  
2. Prefer: delete docs in Admin and **re-upload** per company (re-embed into correct NS)  
3. Or in Pinecone console: delete namespaces that mixed data, then re-upload  
4. Redeploy app with isolation fixes (tenant filter + require company key)  
5. Re-test: Core Tech chat must never mention QuizForge  

---

## Code guarantees (after fix deploy)

| Layer | Guarantee |
|-------|-----------|
| `/query` | Rejects keys with no `tenant_id` when AUTH is on |
| `/query` | Namespace always reloaded from Postgres tenant row |
| `/query` | Pinecone filter `tenant_id` |
| Admin upload | Namespace = tenant.pinecone_namespace; metadata stamped |
| Reprocess | Namespace re-synced from tenant before upsert |
| Delete doc | Deletes Pinecone vectors for that document in company NS |
| Ingest API | Forces principal.namespace; stamps tenant_id when present |

---

## Mental model (one line)

**Company key → Postgres company → Pinecone namespace + tenant_id → only that company’s docs.**
