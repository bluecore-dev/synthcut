"""phases 6/9/11/12 without a model: edit_plans, renders

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 08:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations are additive (ADR-0006): no DROP or RENAME of anything a running
# release still reads, so an image rollback never needs a schema downgrade.


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _project_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"], ["projects.id"], name=op.f(f"fk_{table}_project_id_projects"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "edit_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("clip_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint("source IN ('rules', 'director', 'user')", name=op.f("ck_edit_plans_source")),
        _project_fk("edit_plans"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edit_plans")),
    )
    op.create_index("uq_edit_plans_project_version", "edit_plans", ["project_id", "version"], unique=True)
    op.create_table(
        "renders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("step", sa.Text(), nullable=True),
        sa.Column("output_key", sa.Text(), nullable=True),
        sa.Column("poster_key", sa.Text(), nullable=True),
        sa.Column("telegram_key", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("qa", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("qa_status", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("deliver", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("delivery_status", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_renders_status")
        ),
        sa.CheckConstraint("kind IN ('final')", name=op.f("ck_renders_kind")),
        sa.CheckConstraint(
            "qa_status IS NULL OR qa_status IN ('pass', 'warn', 'fail')", name=op.f("ck_renders_qa_status")
        ),
        sa.CheckConstraint(
            "delivery_status IN ('none', 'queued', 'sent', 'failed')", name=op.f("ck_renders_delivery_status")
        ),
        _project_fk("renders"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["edit_plans.id"], name=op.f("fk_renders_plan_id_edit_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renders")),
    )
    op.create_index(
        "uq_renders_plan_preset_kind",
        "renders",
        ["project_id", "plan_version", "preset", "kind"],
        unique=True,
    )
    op.create_index("ix_renders_project_created", "renders", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_renders_project_created", table_name="renders")
    op.drop_index("uq_renders_plan_preset_kind", table_name="renders")
    op.drop_table("renders")
    op.drop_index("uq_edit_plans_project_version", table_name="edit_plans")
    op.drop_table("edit_plans")
