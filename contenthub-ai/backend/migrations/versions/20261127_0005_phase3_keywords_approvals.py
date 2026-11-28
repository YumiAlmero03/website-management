"""Phase 3 SEO keyword mapping, approval workflow, and revision history tables

Revision ID: 20261127_0005
Revises: 20261127_0004
Create Date: 2026-11-27 18:00:00.000000
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20261127_0005"
down_revision: str | None = "20261127_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def _normalize_focus_phrase(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()[:255]


def upgrade() -> None:
    op.create_table(
        "content_keywords",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=False),
        sa.Column("focus_keyphrase", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "focus_keyphrase_norm", sa.String(length=255), nullable=False, server_default=""
        ),
        sa.Column("secondary_keywords_json", sa.JSON(), nullable=False),
        sa.Column("anchor_text_variations_json", sa.JSON(), nullable=False),
        sa.Column("image_alt_suggestions_json", sa.JSON(), nullable=False),
        sa.Column(
            "approval_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column(
            "suggestion_source",
            sa.String(length=32),
            nullable=False,
            server_default="python_auto",
        ),
        sa.Column("is_admin_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_content_keywords_website_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_content_keywords_content_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_content_keywords_approved_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_content_keywords_created_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("website_content_id", name="uq_content_keywords_content_id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_content_keywords_website_status",
        "content_keywords",
        ["website_id", "approval_status"],
    )
    op.create_index(
        "ix_content_keywords_website_norm",
        "content_keywords",
        ["website_id", "focus_keyphrase_norm"],
    )

    op.create_table(
        "content_keyword_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("content_keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("focus_keyphrase", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("secondary_keywords_json", sa.JSON(), nullable=False),
        sa.Column("anchor_text_variations_json", sa.JSON(), nullable=False),
        sa.Column("image_alt_suggestions_json", sa.JSON(), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("suggestion_source", sa.String(length=32), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column("changed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["content_keyword_id"],
            ["content_keywords.id"],
            name="fk_content_keyword_revisions_kw_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_content_keyword_revisions_user",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "content_keyword_id",
            "revision_number",
            name="uq_content_keyword_revisions_num",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_content_keyword_revisions_kw",
        "content_keyword_revisions",
        ["content_keyword_id"],
    )

    op.create_table(
        "content_approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column(
            "classified_content_type",
            sa.String(length=32),
            nullable=False,
            server_default="page",
        ),
        sa.Column("submitted_content_hash", sa.String(length=64), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("auto_generation_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_content_approvals_website_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_content_approvals_content_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_content_approvals_reviewed_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("website_content_id", name="uq_content_approvals_content_id"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_content_approvals_website_status",
        "content_approvals",
        ["website_id", "status"],
    )
    op.create_index(
        "ix_content_approvals_status_updated",
        "content_approvals",
        ["status", "updated_at"],
    )

    op.create_table(
        "content_approval_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("content_approval_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=True),
        sa.Column("focus_keyphrase", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("acted_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["content_approval_id"],
            ["content_approvals.id"],
            name="fk_content_approval_history_approval_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["acted_by"],
            ["users.id"],
            name="fk_content_approval_history_user",
            ondelete="SET NULL",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_content_approval_history_approval",
        "content_approval_history",
        ["content_approval_id"],
    )
    op.create_index(
        "ix_content_approval_history_created",
        "content_approval_history",
        ["created_at"],
    )

    # Non-destructive backfill for existing eligible website_contents when online.
    if not context.is_offline_mode():
        conn = op.get_bind()
        rows = conn.execute(
            sa.text(
                "SELECT id, website_id, content_type, title, h1_text, keywords, "
                "extraction_status, content_hash "
                "FROM website_contents "
                "WHERE is_excluded = 0 "
                "AND content_type IN ('homepage', 'page', 'blog_post')"
            )
        ).mappings().all()
        for row in rows:
            ext_status = str(row["extraction_status"] or "pending")
            queue_status = (
                "pending_review" if ext_status == "extracted" else "awaiting_extraction"
            )
            raw_keywords = row["keywords"]
            if isinstance(raw_keywords, str):
                try:
                    parsed_kw = json.loads(raw_keywords)
                except ValueError:
                    parsed_kw = []
            elif isinstance(raw_keywords, list):
                parsed_kw = raw_keywords
            else:
                parsed_kw = []
            kw_list = [str(k).strip() for k in parsed_kw if str(k).strip()]
            raw_focus = kw_list[0] if kw_list else (row["h1_text"] or row["title"] or "")
            focus = str(raw_focus).strip()[:255]
            secondary = [k for k in kw_list[1:8] if k.lower() != focus.lower()]
            anchor_variations = [focus] if focus else []

            kw_res = conn.execute(
                sa.text(
                    "INSERT INTO content_keywords "
                    "(website_id, website_content_id, focus_keyphrase, focus_keyphrase_norm, "
                    "secondary_keywords_json, anchor_text_variations_json, "
                    "image_alt_suggestions_json, approval_status, suggestion_source, "
                    "is_admin_locked, version) "
                    "VALUES (:wid, :cid, :fk, :fkn, :sec, :anc, :alt, :st, 'backfill', 0, 1)"
                ),
                {
                    "wid": row["website_id"],
                    "cid": row["id"],
                    "fk": focus,
                    "fkn": _normalize_focus_phrase(focus),
                    "sec": json.dumps(secondary),
                    "anc": json.dumps(anchor_variations),
                    "alt": json.dumps([]),
                    "st": queue_status,
                },
            )
            kw_id = int(kw_res.lastrowid)
            conn.execute(
                sa.text(
                    "INSERT INTO content_keyword_revisions "
                    "(content_keyword_id, revision_number, focus_keyphrase, "
                    "secondary_keywords_json, anchor_text_variations_json, "
                    "image_alt_suggestions_json, approval_status, suggestion_source, change_note) "
                    "VALUES (:kwid, 1, :fk, :sec, :anc, :alt, :st, 'backfill', "
                    "'Initial non-destructive migration backfill')"
                ),
                {
                    "kwid": kw_id,
                    "fk": focus,
                    "sec": json.dumps(secondary),
                    "anc": json.dumps(anchor_variations),
                    "alt": json.dumps([]),
                    "st": queue_status,
                },
            )

            app_res = conn.execute(
                sa.text(
                    "INSERT INTO content_approvals "
                    "(website_id, website_content_id, status, classified_content_type, "
                    "submitted_content_hash, review_note) "
                    "VALUES (:wid, :cid, :st, :ctype, :chash, "
                    "'Backfilled during keyword & approval schema upgrade')"
                ),
                {
                    "wid": row["website_id"],
                    "cid": row["id"],
                    "st": queue_status,
                    "ctype": row["content_type"],
                    "chash": row["content_hash"],
                },
            )
            app_id = int(app_res.lastrowid)
            conn.execute(
                sa.text(
                    "INSERT INTO content_approval_history "
                    "(content_approval_id, from_status, to_status, content_type, "
                    "focus_keyphrase, action, note) "
                    "VALUES (:aid, NULL, :st, :ctype, :fk, 'created', "
                    "'Backfilled pending review record (never auto-approved)')"
                ),
                {
                    "aid": app_id,
                    "st": queue_status,
                    "ctype": row["content_type"],
                    "fk": focus or None,
                },
            )


def downgrade() -> None:
    op.drop_table("content_approval_history")
    op.drop_table("content_approvals")
    op.drop_table("content_keyword_revisions")
    op.drop_table("content_keywords")
