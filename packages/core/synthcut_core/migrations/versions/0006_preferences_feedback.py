"""phase 10 without a model: preferences, feedback

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations are additive (ADR-0006): no DROP or RENAME of anything a running
# release still reads, so an image rollback never needs a schema downgrade.


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("render_id", sa.Uuid(), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=True),
        sa.Column(
            "codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("at_sec", sa.Float(), nullable=True),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_feedback_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_feedback_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["render_id"], ["renders.id"], name=op.f("fk_feedback_render_id_renders"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index("ix_feedback_project_created", "feedback", ["project_id", "created_at"], unique=False)
    op.create_table(
        "preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("feedback_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("scope IN ('user', 'project')", name=op.f("ck_preferences_scope")),
        sa.CheckConstraint("source IN ('choice', 'feedback', 'agent')", name=op.f("ck_preferences_source")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_preferences_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["feedback.id"],
            name=op.f("fk_preferences_feedback_id_feedback"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preferences")),
    )
    op.create_index(
        "uq_preferences_user_key",
        "preferences",
        ["user_id", "key"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_preferences_project_key",
        "preferences",
        ["user_id", "project_id", "key"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_preferences_project_key", table_name="preferences")
    op.drop_index("uq_preferences_user_key", table_name="preferences")
    op.drop_table("preferences")
    op.drop_index("ix_feedback_project_created", table_name="feedback")
    op.drop_table("feedback")
