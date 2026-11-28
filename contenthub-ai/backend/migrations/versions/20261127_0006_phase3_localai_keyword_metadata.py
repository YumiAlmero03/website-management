"""Phase 3 LocalAI and keyword metadata

Revision ID: 20261127_0006
Revises: 20261127_0005
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261127_0006"
down_revision: str | None = "20261127_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_providers", sa.Column("base_url", sa.String(length=500), nullable=True))

    op.add_column(
        "content_keywords",
        sa.Column("keyword_generation_method", sa.String(length=32), nullable=False,
                  server_default="python"),
    )
    op.add_column(
        "content_keywords",
        sa.Column("keyword_generation_status", sa.String(length=32), nullable=False,
                  server_default="pending"),
    )
    op.add_column(
        "content_keywords",
        sa.Column("keyword_evidence_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "content_keywords",
        sa.Column("keyword_scores_json", sa.JSON(), nullable=True),
    )
    op.execute("UPDATE content_keywords SET keyword_evidence_json = '[]' WHERE keyword_evidence_json IS NULL")
    op.execute("UPDATE content_keywords SET keyword_scores_json = '{}' WHERE keyword_scores_json IS NULL")
    op.alter_column("content_keywords", "keyword_evidence_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("content_keywords", "keyword_scores_json", existing_type=sa.JSON(), nullable=False)
    op.add_column("content_keywords", sa.Column("keyword_model", sa.String(length=120), nullable=True))
    op.add_column("content_keywords", sa.Column("keyword_input_hash", sa.String(length=64), nullable=True))
    op.add_column("content_keywords", sa.Column("keyword_generated_at", sa.DateTime(), nullable=True))
    op.add_column("content_keywords", sa.Column("game_name", sa.String(length=255), nullable=True))
    op.add_column("content_keywords", sa.Column("provider_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    for name in (
        "provider_name", "game_name", "keyword_generated_at", "keyword_input_hash",
        "keyword_model", "keyword_scores_json", "keyword_evidence_json",
        "keyword_generation_status", "keyword_generation_method",
    ):
        op.drop_column("content_keywords", name)
    op.drop_column("ai_providers", "base_url")
