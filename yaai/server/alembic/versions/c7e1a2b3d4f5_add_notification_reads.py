"""add per-reader notification read state

Revision ID: c7e1a2b3d4f5
Revises: b4d9e2f1a8c3
Create Date: 2026-10-16 00:00:00.000000

Read state was a single global flag on notifications, so one user marking a
notification as read hid it for everybody. Read state is now stored per user or
service account in notification_reads. notifications.is_read is kept as the
global fallback for deployments running with authentication disabled.

Existing notifications with is_read = true are backfilled as read for every
existing user, preserving what users currently see.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e1a2b3d4f5"
down_revision: str | None = "b4d9e2f1a8c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("service_account_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (service_account_id IS NULL)",
            name="ck_notification_reads_one_reader",
        ),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_account_id"], ["service_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_user"),
        sa.UniqueConstraint("notification_id", "service_account_id", name="uq_notification_reads_sa"),
    )
    op.create_index("ix_notification_reads_notification", "notification_reads", ["notification_id"])

    # gen_random_uuid() is built in since PostgreSQL 13
    op.execute(
        """
        INSERT INTO notification_reads (id, notification_id, user_id)
        SELECT gen_random_uuid(), n.id, u.id
        FROM notifications n
        CROSS JOIN users u
        WHERE n.is_read = true
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notification_reads_notification", table_name="notification_reads")
    op.drop_table("notification_reads")
