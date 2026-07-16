# RAG API Platform

**Backend multi-tenant RAG service** for other companies.

Clients integrate with **API keys + HTTP endpoints**.  
This is **not** a chat product — optional Admin UI is for **operators only**.

Stack: FastAPI · LangChain · HF embeddings · Pinecone · OpenRouter · Postgres/SQLite · S3/local

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# set OPENROUTER_API_KEY, PINECONE_API_KEY
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| URL | Purpose |
|-----|---------|
| `GET /` | Service descriptor (API-first) |
| `/docs` | OpenAPI contract for partners |
| `/admin` | Operator console (tenants, keys, models) |
| `/api/v1/health` | Liveness |

Chat/dev UIs are **off** by default (`ENABLE_CHAT_UI=false`, `ENABLE_DEV_UI=false`).

## Partner (client company) API

Auth header:

```http
X-API-Key: <tenant_key>
# or
Authorization: Bearer <tenant_key>
```

| Method | Path | Scope |
|--------|------|--------|
| `POST` | `/api/v1/query` | `query:read` |
| `POST` | `/api/v1/ingest` | `ingest:write` |
| `POST` | `/api/v1/ingest/file` | `ingest:write` |
| `GET/POST` | `/api/v1/documents` | `docs:read` / `ingest:write` |

Namespace isolation is **forced from the API key’s tenant** (clients cannot read other corpora).

## Operator (platform admin) flow

1. Use bootstrap `API_KEY_ADMIN` / `BOOTSTRAP_ADMIN_KEY` (env) or a DB platform key.  
2. `POST /api/v1/admin/tenants` → create company.  
3. `POST /api/v1/admin/tenants/{id}/keys` → **copy `api_key` once**.  
4. Upload docs: `POST /api/v1/admin/tenants/{id}/documents` or client `POST /documents`.  
5. Give the tenant key to the other company’s backend.  
6. Configure models: `/api/v1/admin/models`, tenant override via `PATCH .../tenants/{id}/models`.

Admin UI modules: **System · Tenants · Keys · Models · Documents · Usage**.

## Railway

- Dockerfile listens on `$PORT`
- Add **PostgreSQL** → `DATABASE_URL`
- Optional **S3/bucket** for files
- Set secrets in Railway variables (see `.env.example`)
- Pinecone index: **cosine**, **dimension 384**

## Product flags

```env
PRODUCT_MODE=api_platform
ENABLE_CHAT_UI=false
ENABLE_DEV_UI=false
ENABLE_ADMIN_UI=true
AUTH_ENABLED=true   # production
```
```
