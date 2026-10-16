"""add projects and project memberships

Revision ID: d8f2b3c4e5a6
Revises: c7e1a2b3d4f5
Create Date: 2026-10-16 00:00:00.000000

Models now belong to a project and access is granted through project memberships
(owner / editor / viewer). Model names are unique per project instead of globally.

The upgrade creates an open project named "default" that contains all existing models
and makes every existing user a viewer of it, so all users keep reading every model
(global owners keep full access as super-admins). Service accounts keep their per-model
access and are not added as members.

The downgrade drops projects and memberships and restores the global unique constraint
on models.name. It fails if two projects contain models with the same name; rename or
delete one of them first.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f2b3c4e5a6"
down_revision: str | None = "c7e1a2b3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PROJECT_NAME = "default"
GLOBAL_NAME_UNIQUE = "models_name_key"  # PostgreSQL's default name for the unnamed constraint of the initial schema


def _global_name_unique_constraints() -> list[str]:
    """Names of unique constraints on models.name alone, looked up so custom names are handled too."""
    inspector = sa.inspect(op.get_bind())
    return [
        c["name"] for c in inspector.get_unique_constraints("models") if c["column_names"] == ["name"] and c.get("name")
    ]


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("service_account_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.Enum("OWNER", "EDITOR", "VIEWER", name="projectrole"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (service_account_id IS NULL)",
            name="ck_project_memberships_one_principal",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_account_id"], ["service_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_memberships_user"),
        sa.UniqueConstraint("service_account_id", "project_id", name="uq_project_memberships_sa"),
    )
    op.create_index("ix_project_memberships_project", "project_memberships", ["project_id"])

    default_project_id = uuid.uuid4()
    op.execute(
        sa.text("INSERT INTO projects (id, name, description) VALUES (:id, :name, :description)").bindparams(
            id=default_project_id,
            name=DEFAULT_PROJECT_NAME,
            description="Contains all models that existed before projects were introduced.",
        )
    )

    op.add_column("models", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.execute(sa.text("UPDATE models SET project_id = :id").bindparams(id=default_project_id))
    op.alter_column("models", "project_id", nullable=False)
    op.create_foreign_key("fk_models_project_id", "models", "projects", ["project_id"], ["id"], ondelete="RESTRICT")

    for name in _global_name_unique_constraints():
        op.drop_constraint(name, "models", type_="unique")
    op.create_unique_constraint("uq_model_project_name", "models", ["project_id", "name"])

    # gen_random_uuid() is built in since PostgreSQL 13
    op.execute(
        sa.text(
            "INSERT INTO project_memberships (id, project_id, user_id, role) "
            "SELECT gen_random_uuid(), :project_id, id, 'VIEWER' FROM users"
        ).bindparams(project_id=default_project_id)
    )


def downgrade() -> None:
    duplicates = op.get_bind().execute(sa.text("SELECT name FROM models GROUP BY name HAVING count(*) > 1")).all()
    if duplicates:
        names = ", ".join(sorted(row[0] for row in duplicates))
        raise RuntimeError(
            f"Cannot downgrade: model names must be globally unique again but these exist in several projects: {names}. "
            "Rename or delete the duplicates first."
        )

    op.drop_constraint("uq_model_project_name", "models", type_="unique")
    op.create_unique_constraint(GLOBAL_NAME_UNIQUE, "models", ["name"])
    op.drop_constraint("fk_models_project_id", "models", type_="foreignkey")
    op.drop_column("models", "project_id")

    op.drop_index("ix_project_memberships_project", table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_table("projects")
    sa.Enum(name="projectrole").drop(op.get_bind(), checkfirst=True)
