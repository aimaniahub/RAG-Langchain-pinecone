# Company RAG — Railway / production Docker image
# Listens on $PORT (Railway injects this). Postgres + S3 via env vars.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf \
    TRANSFORMERS_CACHE=/models/hf \
    SENTENCE_TRANSFORMERS_HOME=/models/hf \
    PORT=8000 \
    APP_ENV=production \
    AUTO_MIGRATE=true

WORKDIR /app

# System deps: build wheels + Postgres client libs for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# CPU PyTorch first (smaller / more reliable on Railway than default CUDA wheels)
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY README.md ./README.md

RUN useradd -m -u 10001 appuser \
    && mkdir -p /models/hf /app/data/uploads \
    && chown -R appuser:appuser /app /models

USER appuser

# Railway maps public traffic to container $PORT
EXPOSE 8000

# Container-level health (Railway also uses railway.toml healthcheckPath)
HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=5 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/v1/health', timeout=5)" || exit 1

# Shell form so ${PORT} expands (JSON CMD does not)
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
