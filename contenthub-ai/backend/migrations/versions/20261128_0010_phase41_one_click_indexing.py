"""Phase 4.1 one-click Google indexing and backlink tracking."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261128_0010"
down_revision: str | None = "20261128_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.add_column("websites", sa.Column("gsc_property_url", sa.String(500), nullable=True))
    op.add_column("websites", sa.Column("gsc_property_verified_at", sa.DateTime(), nullable=True))

    op.add_column(
        "website_contents",
        sa.Column(
            "google_index_status",
            sa.String(32),
            nullable=False,
            server_default="uninspected",
        ),
    )
    op.add_column(
        "website_contents",
        sa.Column("google_index_verified_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "website_contents",
        sa.Column("google_index_last_attempt_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "website_contents",
        sa.Column("google_index_coverage_state", sa.String(100), nullable=True),
    )
    op.add_column(
        "website_contents",
        sa.Column("google_index_verdict", sa.String(100), nullable=True),
    )
    op.add_column(
        "website_contents",
        sa.Column("google_index_inspection_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_website_contents_google_index",
        "website_contents",
        ["website_id", "google_index_status", "google_index_last_attempt_at"],
    )

    op.add_column(
        "social_posts",
        sa.Column(
            "backlink_status",
            sa.String(32),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column(
        "social_posts",
        sa.Column("backlink_checked_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "indexing_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_uuid", sa.String(64), nullable=False),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_ids_json", sa.JSON(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("deferred_reason", sa.String(500), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
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
            ["website_id"], ["websites.id"], name="fk_index_job_website", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_uuid", name="uq_index_job_uuid"),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_indexing_jobs_claim",
        "indexing_jobs",
        ["website_id", "status", "available_at"],
    )

    op.create_table(
        "indexing_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("website_id", sa.BigInteger(), nullable=False),
        sa.Column("website_content_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("inspection_status", sa.String(100), nullable=True),
        sa.Column("technical_status", sa.String(100), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            ["job_id"], ["indexing_jobs.id"], name="fk_index_history_job", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["websites.id"], name="fk_index_history_website", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["website_content_id"],
            ["website_contents.id"],
            name="fk_index_history_content",
            ondelete="CASCADE",
        ),
        **MYSQL_TABLE_ARGS,
    )
    op.create_index(
        "ix_indexing_history_site_content",
        "indexing_history",
        ["website_id", "website_content_id"],
    )


def downgrade() -> None:
    op.drop_table("indexing_history")
    op.drop_table("indexing_jobs")
    op.drop_index("ix_website_contents_google_index", table_name="website_contents")
    for col in (
        "google_index_inspection_json",
        "google_index_verdict",
        "google_index_coverage_state",
        "google_index_last_attempt_at",
        "google_index_verified_at",
        "google_index_status",
    ):
        op.drop_column("website_contents", col)
    op.drop_column("social_posts", "backlink_checked_at")
    op.drop_column("social_posts", "backlink_status")
    op.drop_column("websites", "gsc_property_verified_at")
    op.drop_column("websites", "gsc_property_url")
