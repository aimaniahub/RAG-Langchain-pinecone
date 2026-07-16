"""Per-company RAG settings on tenants.

Revision ID: 002_tenant_rag
Revises: 001_initial
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_tenant_rag"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("top_k", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("return_top_n", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("max_context_chars", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("max_question_chars", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("max_chars_per_chunk", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("temperature", sa.Float(), nullable=True))
    op.add_column("tenants", sa.Column("min_retrieval_score", sa.Float(), nullable=True))
    op.add_column("tenants", sa.Column("rerank_enabled", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("answer_cache_enabled", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("no_context_message", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in (
        "system_prompt",
        "top_k",
        "return_top_n",
        "max_context_chars",
        "max_question_chars",
        "max_chars_per_chunk",
        "temperature",
        "min_retrieval_score",
        "rerank_enabled",
        "answer_cache_enabled",
        "no_context_message",
    ):
        op.drop_column("tenants", col)
