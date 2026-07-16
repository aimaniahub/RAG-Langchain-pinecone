# RAG API Platform

**Enterprise multi-tenant RAG backend** for other companies.

- Clients integrate with **API keys + HTTP endpoints** (not a chat product)
- Operators use **`/admin`**: setup, companies desk, Test API, users, system
- Data in **Postgres** (or SQLite locally): tenants, users, memberships, keys, documents, usage

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| URL | Purpose |
|-----|---------|
| `/` | API service descriptor |
| `/admin` | Operator console |
| `/docs` | Partner OpenAPI |
| `/api/v1/health` | Health |

Admin key default: `dev-admin-key` (`API_KEY_ADMIN`)

## Admin usage

1. **Home** — live checklist from DB  
2. **Companies → Add company** — tenant + API key (copy once)  
3. **Configure** — Overview (integration card + copy), Keys, Documents, Models, Users, Usage  
4. **Test API** — select company by name → issue test key → chat via real `POST /query`  
5. Share base URL + key with the client company  

Set `PUBLIC_BASE_URL` on Railway so the Integration card shows your public domain.

## Client API

```http
X-API-Key: rag_live_...
POST /api/v1/query
POST /api/v1/ingest
POST /api/v1/ingest/file
GET  /api/v1/documents
```

## Postgres (production)

```env
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
API_KEY_ADMIN=<strong>
PUBLIC_BASE_URL=https://your-service.up.railway.app
```

Tables are created on boot when `AUTO_MIGRATE=true`.

**Do not push until you approve.**
```
