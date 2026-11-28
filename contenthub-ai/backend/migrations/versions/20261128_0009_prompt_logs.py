"""Store encrypted AI prompt exchanges alongside usage history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision: str = "20261128_0009"
down_revision: str | None = "20261128_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_generation_logs",
        sa.Column("encrypted_prompt_exchange", sa.Text().with_variant(MEDIUMTEXT(), "mysql")),
    )


def downgrade() -> None:
    op.drop_column("ai_generation_logs", "encrypted_prompt_exchange")
