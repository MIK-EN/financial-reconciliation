"""Create immutable onboarding content and progress storage.

Revision ID: 0001_onboarding
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_onboarding"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_bundles",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_content_bundles_content_hash_sha256_length",
        ),
        sa.PrimaryKeyConstraint("version", name="pk_content_bundles"),
        sa.UniqueConstraint("content_hash", name="uq_content_bundles_content_hash"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("current_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("csrf_secret", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_browser_sessions_token_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "kind IN ('anonymous', 'authenticated')",
            name="ck_browser_sessions_kind_valid",
        ),
        sa.CheckConstraint(
            "(kind = 'anonymous' AND user_id IS NULL) OR "
            "(kind = 'authenticated' AND user_id IS NOT NULL)",
            name="ck_browser_sessions_owner_matches_kind",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_browser_sessions_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_browser_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_browser_sessions_token_hash"),
    )
    op.create_table(
        "content_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("active_version", sa.String(length=64), nullable=False),
        sa.Column("threshold_percent", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_content_settings_singleton_row"),
        sa.CheckConstraint(
            "threshold_percent BETWEEN 0 AND 100",
            name="ck_content_settings_threshold_range",
        ),
        sa.ForeignKeyConstraint(
            ["active_version"],
            ["content_bundles.version"],
            name="fk_content_settings_active_version_content_bundles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_content_settings"),
    )
    op.create_table(
        "onboarding_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anonymous_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_version", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("threshold_percent", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommended_level", sa.String(length=32), nullable=True),
        sa.Column("selected_level", sa.String(length=32), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'active' AND completed_at IS NULL AND recommended_level IS NULL "
            "AND selected_level IS NULL AND reason_code IS NULL) OR "
            "(status = 'completed' AND completed_at IS NOT NULL "
            "AND recommended_level IS NOT NULL AND selected_level IS NOT NULL "
            "AND reason_code IS NOT NULL)",
            name="ck_onboarding_runs_completion_fields_consistent",
        ),
        sa.CheckConstraint(
            "(user_id IS NULL AND claimed_at IS NULL) OR "
            "(user_id IS NOT NULL AND claimed_at IS NOT NULL AND status = 'completed')",
            name="ck_onboarding_runs_claim_fields_consistent",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_onboarding_runs_revision_nonnegative"),
        sa.CheckConstraint(
            "status IN ('active', 'completed')", name="ck_onboarding_runs_status_valid"
        ),
        sa.CheckConstraint(
            "threshold_percent BETWEEN 0 AND 100",
            name="ck_onboarding_runs_threshold_range",
        ),
        sa.ForeignKeyConstraint(
            ["anonymous_session_id"],
            ["browser_sessions.id"],
            name="fk_onboarding_runs_anonymous_session_id_browser_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["content_version"],
            ["content_bundles.version"],
            name="fk_onboarding_runs_content_version_content_bundles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_onboarding_runs_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_onboarding_runs"),
        sa.UniqueConstraint("anonymous_session_id", name="uq_onboarding_runs_anonymous_session_id"),
        sa.UniqueConstraint("id", "user_id", name="uq_onboarding_runs_id_user_id"),
    )
    op.create_table(
        "onboarding_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("text_id", sa.String(length=32), nullable=False),
        sa.Column("answer_mode", sa.String(length=16), nullable=True),
        sa.Column("unknown_word_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unknown_count", sa.SmallInteger(), nullable=True),
        sa.Column("total_word_count", sa.SmallInteger(), nullable=True),
        sa.Column("accessible", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(answer_mode IS NULL AND unknown_word_ids IS NULL AND unknown_count IS NULL "
            "AND total_word_count IS NULL AND accessible IS NULL AND answered_at IS NULL) "
            "OR (answer_mode IN ('all_known', 'unknown_words') "
            "AND unknown_word_ids IS NOT NULL AND unknown_count IS NOT NULL "
            "AND total_word_count IS NOT NULL AND accessible IS NOT NULL "
            "AND answered_at IS NOT NULL AND jsonb_typeof(unknown_word_ids) = 'array' "
            "AND jsonb_array_length(unknown_word_ids) = unknown_count "
            "AND unknown_count BETWEEN 0 AND total_word_count AND total_word_count > 0 "
            "AND ((answer_mode = 'all_known' AND unknown_count = 0) OR "
            "(answer_mode = 'unknown_words' AND unknown_count > 0)))",
            name="ck_onboarding_steps_answer_consistency",
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 4", name="ck_onboarding_steps_ordinal_range"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["onboarding_runs.id"],
            name="fk_onboarding_steps_run_id_onboarding_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_onboarding_steps"),
        sa.UniqueConstraint("id", "run_id", name="uq_onboarding_steps_id_run"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_onboarding_steps_run_ordinal"),
        sa.UniqueConstraint("run_id", "text_id", name="uq_onboarding_steps_run_text"),
    )
    op.create_index(
        "uq_onboarding_steps_one_unanswered_per_run",
        "onboarding_steps",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("answered_at IS NULL"),
    )
    op.create_foreign_key(
        "fk_users_current_run_owned",
        "users",
        "onboarding_runs",
        ["current_run_id", "id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_onboarding_runs_current_step",
        "onboarding_runs",
        "onboarding_steps",
        ["current_step_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_onboarding_runs_current_step", "onboarding_runs", type_="foreignkey")
    op.drop_constraint("fk_users_current_run_owned", "users", type_="foreignkey")
    op.drop_index("uq_onboarding_steps_one_unanswered_per_run", table_name="onboarding_steps")
    op.drop_table("onboarding_steps")
    op.drop_table("onboarding_runs")
    op.drop_table("content_settings")
    op.drop_table("browser_sessions")
    op.drop_table("users")
    op.drop_table("content_bundles")
