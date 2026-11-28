"""Add website keyword bank for editorial keyword references."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261128_0007"
down_revision: str | None = "20261127_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("websites", sa.Column("keyword_bank", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("websites", "keyword_bank")
