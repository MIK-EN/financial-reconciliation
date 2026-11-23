"""Store Telegram identities and browser session nonces.

Revision ID: 0003_telegram_identities
Revises: 0002_unanswered_step
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_telegram_identities"
down_revision: str | Sequence[str] | None = "0002_unanswered_step"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "username", nullable=True)
    op.alter_column("users", "password_hash", nullable=True)
    op.create_check_constraint(
        op.f("ck_users_credentials_pair"),
        "users",
        "(username IS NULL) = (password_hash IS NULL)",
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_identities"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_identities_user_id_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "provider IN ('telegram')", name=op.f("ck_auth_identities_provider_valid")
        ),
        sa.CheckConstraint(
            "length(subject) > 0", name=op.f("ck_auth_identities_subject_not_empty")
        ),
        sa.UniqueConstraint("provider", "subject", name="uq_auth_identities_provider_subject"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])

    op.add_column("browser_sessions", sa.Column("telegram_nonce_hash", sa.String(length=64)))
    op.add_column(
        "browser_sessions", sa.Column("telegram_nonce_expires_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        op.f("ck_browser_sessions_telegram_nonce_valid"),
        "browser_sessions",
        "(telegram_nonce_hash IS NULL AND telegram_nonce_expires_at IS NULL) OR "
        "(telegram_nonce_hash IS NOT NULL AND telegram_nonce_expires_at IS NOT NULL "
        "AND length(telegram_nonce_hash) = 64 AND kind = 'anonymous')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_browser_sessions_telegram_nonce_valid"), "browser_sessions", type_="check"
    )
    op.drop_column("browser_sessions", "telegram_nonce_expires_at")
    op.drop_column("browser_sessions", "telegram_nonce_hash")

    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")

    op.drop_constraint(op.f("ck_users_credentials_pair"), "users", type_="check")
    # Restoring NOT NULL may fail if password-less users exist.
    op.alter_column("users", "password_hash", nullable=False)
    op.alter_column("users", "username", nullable=False)
