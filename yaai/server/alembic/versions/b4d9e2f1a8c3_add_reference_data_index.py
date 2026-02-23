"""add index on reference_data(model_version_id)

Revision ID: b4d9e2f1a8c3
Revises: 7f3c318ce50f
Create Date: 2026-02-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d9e2f1a8c3"
down_revision: str | None = "7f3c318ce50f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_reference_version", "reference_data", ["model_version_id"])


def downgrade() -> None:
    op.drop_index("ix_reference_version", table_name="reference_data")
