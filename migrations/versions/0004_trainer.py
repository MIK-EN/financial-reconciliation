"""Add independent trainer content; existing onboarding and accounts are unchanged.

Revision ID: 0004_trainer
Revises: 0003_telegram_identities
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_trainer"
down_revision = "0003_telegram_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_bundles",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(content_hash) = 64", name="content_hash_sha256_length"),
    )
    op.create_table(
        "trainer_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "active_version",
            sa.String(64),
            sa.ForeignKey("trainer_bundles.version", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="singleton_row"),
    )


def downgrade() -> None:
    op.drop_table("trainer_settings")
    op.drop_table("trainer_bundles")
