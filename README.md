# Company RAG (LangChain · Pinecone · FastAPI)

Production-oriented RAG API with:

- **Embeddings:** free local HuggingFace `all-MiniLM-L6-v2` (384-d)
- **LLM:** OpenRouter (OpenAI-compatible)
- **Vectors:** Pinecone
- **API / UI:** FastAPI · Chat (`/chat`) · Admin (`/admin`)
- **Data:** PostgreSQL (Railway) or SQLite (local)
- **Files:** S3-compatible bucket (Railway) or `./data/uploads` (local)

## Local run (conda)

```bash
conda env create -f environment.yml
conda activate rag-company
cp .env.example .env   # Windows: copy .env.example .env
# set OPENROUTER_API_KEY + PINECONE_API_KEY

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| URL | Purpose |
|-----|---------|
| `/chat` | Persistent chat |
| `/admin` | Upload docs → auto-embed, usage, monitors |
| `/ui` | Dev console |
| `/docs` | OpenAPI |
| `/api/v1/health` | Liveness (Railway healthcheck) |
| `/api/v1/ready` | DB / storage / OpenRouter / Pinecone |

## Docker (image used by Railway)

```bash
docker build -t company-rag .
docker run --rm -p 8000:8000 --env-file .env -e PORT=8000 company-rag
```

Local stack with Postgres:

```bash
docker compose up --build
```

## Railway deploy

### 1. Plugins (same Railway project)

| Plugin / resource | Purpose | Wire as |
|-------------------|---------|---------|
| **PostgreSQL** | chats, documents, usage | `DATABASE_URL=${{Postgres.DATABASE_URL}}` |
| **Object storage / S3** (or external S3) | company file uploads | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `S3_REGION` |
| **Web service** (this repo) | Dockerfile app | auto `$PORT` |

Without S3, the app falls back to **local disk** (`LOCAL_STORAGE_DIR`) — fine for tiny demos, not multi-instance prod.

### 2. Required variables

```env
APP_ENV=production
AUTH_ENABLED=true
AUTO_MIGRATE=true
DATABASE_URL=${{Postgres.DATABASE_URL}}

OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=company-rag
PINECONE_NAMESPACE=default

API_KEY_ADMIN=...strong-secret...
API_KEY_USER=...strong-secret...

# Optional S3
S3_ENDPOINT_URL=...
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=...
S3_REGION=auto

# If OOM on small plan
# RERANK_ENABLED=false
# WARMUP_EMBEDDINGS=false
```

### 3. Deploy notes

- Image is **Dockerfile-based** (`railway.toml`)
- App **must listen on `$PORT`** (already configured)
- Healthcheck path: **`/api/v1/health`** (timeout 300s for first HF download)
- Pinecone index metric **cosine**, dimension **384**
- Prefer a **stable** OpenRouter model in production (avoid free-tier 429s)

### 4. After deploy

1. Open `https://<service>.up.railway.app/admin`
2. Upload a company PDF/MD/TXT (admin key)
3. Open `/chat` and ask grounded questions

## Project layout

```
app/           # API, RAG, DB, storage, static UIs
alembic/       # SQL migrations
scripts/       # create_pinecone_index, ingest_sample
Dockerfile     # Railway image
railway.toml   # build + healthcheck
```

## License

Private / company use unless stated otherwise.
```
