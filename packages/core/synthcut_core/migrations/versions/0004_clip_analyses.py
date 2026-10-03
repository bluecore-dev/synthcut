"""phase 5 analysis: asset_analyses, clip_analyses

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Migrations are additive (ADR-0006): no DROP or RENAME of anything a running
# release still reads, so an image rollback never needs a schema downgrade.


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _owner_fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f(f"fk_{table}_asset_id_assets"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f(f"fk_{table}_project_id_projects"), ondelete="CASCADE"
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "asset_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("clip_count", sa.Integer(), nullable=True),
        sa.Column("usable_avg", sa.Float(), nullable=True),
        sa.Column("sample_fps", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_asset_analyses_status")
        ),
        *_owner_fks("asset_analyses"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_analyses")),
        sa.UniqueConstraint("asset_id", name=op.f("uq_asset_analyses_asset_id")),
    )
    op.create_index("ix_asset_analyses_project", "asset_analyses", ["project_id"], unique=False)
    op.create_table(
        "clip_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("clip_id", sa.Text(), nullable=False),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        sa.Column("shot_type", sa.Text(), nullable=False),
        sa.Column("camera_motion", sa.Text(), nullable=False),
        sa.Column("usable_score", sa.Float(), nullable=False),
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("dhash", sa.Text(), nullable=True),
        sa.Column("sheet_key", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        *_owner_fks("clip_analyses"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clip_analyses")),
    )
    op.create_index("ix_clip_analyses_project", "clip_analyses", ["project_id"], unique=False)
    op.create_index("uq_clip_analyses_asset_shot", "clip_analyses", ["asset_id", "shot_index"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_clip_analyses_asset_shot", table_name="clip_analyses")
    op.drop_index("ix_clip_analyses_project", table_name="clip_analyses")
    op.drop_table("clip_analyses")
    op.drop_index("ix_asset_analyses_project", table_name="asset_analyses")
    op.drop_table("asset_analyses")
