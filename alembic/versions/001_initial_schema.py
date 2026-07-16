"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("storage_backend", sa.String(length=32)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("namespace", sa.String(length=128)),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("vector_count", sa.Integer()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id")),
        sa.Column("status", sa.String(length=32)),
        sa.Column("attempts", sa.Integer()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=256)),
        sa.Column("namespace", sa.String(length=128)),
        sa.Column("user_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("chat_sessions.id")),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("timings_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("lag_stage", sa.String(length=64), nullable=True),
        sa.Column("cache_hit", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=32)),
        sa.Column("user_name", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("lag_stage", sa.String(length=64), nullable=True),
        sa.Column("cache_hit", sa.String(length=32), nullable=True),
        sa.Column("context_tokens_est", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("ingest_jobs")
    op.drop_table("documents")
