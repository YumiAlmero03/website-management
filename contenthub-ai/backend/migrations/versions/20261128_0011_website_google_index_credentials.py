"""Store encrypted per-website Google indexing credentials."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261128_0011"
down_revision: str | None = "20261128_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "websites",
        sa.Column("encrypted_gsc_service_account_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("websites", "encrypted_gsc_service_account_json")