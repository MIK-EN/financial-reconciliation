"""PostgreSQL schema for immutable content and onboarding progress."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ContentBundle(Base):
    __tablename__ = "content_bundles"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_content_bundles_content_hash"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256_length"),
    )

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentSettings(Base):
    __tablename__ = "content_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton_row"),
        CheckConstraint("threshold_percent BETWEEN 0 AND 100", name="threshold_range"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    active_version: Mapped[str] = mapped_column(
        ForeignKey("content_bundles.version", ondelete="RESTRICT"), nullable=False
    )
    threshold_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        ForeignKeyConstraint(
            ["current_run_id", "id"],
            ["onboarding_runs.id", "onboarding_runs.user_id"],
            name="fk_users_current_run_owned",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    current_run_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_browser_sessions_token_hash"),
        CheckConstraint("kind IN ('anonymous', 'authenticated')", name="kind_valid"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_sha256_length"),
        CheckConstraint(
            "(kind = 'anonymous' AND user_id IS NULL) OR "
            "(kind = 'authenticated' AND user_id IS NOT NULL)",
            name="owner_matches_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    csrf_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OnboardingRun(Base):
    __tablename__ = "onboarding_runs"
    __table_args__ = (
        UniqueConstraint("anonymous_session_id", name="uq_onboarding_runs_anonymous_session_id"),
        UniqueConstraint("id", "user_id", name="uq_onboarding_runs_id_user_id"),
        ForeignKeyConstraint(
            ["current_step_id", "id"],
            ["onboarding_steps.id", "onboarding_steps.run_id"],
            name="fk_onboarding_runs_current_step",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("threshold_percent BETWEEN 0 AND 100", name="threshold_range"),
        CheckConstraint("status IN ('active', 'completed')", name="status_valid"),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint(
            "(status = 'active' AND completed_at IS NULL AND recommended_level IS NULL "
            "AND selected_level IS NULL AND reason_code IS NULL) OR "
            "(status = 'completed' AND completed_at IS NOT NULL "
            "AND recommended_level IS NOT NULL AND selected_level IS NOT NULL "
            "AND reason_code IS NOT NULL)",
            name="completion_fields_consistent",
        ),
        CheckConstraint(
            "(user_id IS NULL AND claimed_at IS NULL) OR "
            "(user_id IS NOT NULL AND claimed_at IS NOT NULL AND status = 'completed')",
            name="claim_fields_consistent",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    anonymous_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    content_version: Mapped[str] = mapped_column(
        ForeignKey("content_bundles.version", ondelete="RESTRICT"), nullable=False
    )
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_step_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    recommended_level: Mapped[str | None] = mapped_column(String(32))
    selected_level: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OnboardingStep(Base):
    __tablename__ = "onboarding_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_onboarding_steps_run_ordinal"),
        UniqueConstraint("run_id", "text_id", name="uq_onboarding_steps_run_text"),
        UniqueConstraint("id", "run_id", name="uq_onboarding_steps_id_run"),
        ForeignKeyConstraint(["run_id"], ["onboarding_runs.id"], ondelete="RESTRICT"),
        CheckConstraint("ordinal BETWEEN 1 AND 4", name="ordinal_range"),
        CheckConstraint(
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
            name="answer_consistency",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text_id: Mapped[str] = mapped_column(String(32), nullable=False)
    answer_mode: Mapped[str | None] = mapped_column(String(16))
    unknown_word_ids: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    unknown_count: Mapped[int | None] = mapped_column(SmallInteger)
    total_word_count: Mapped[int | None] = mapped_column(SmallInteger)
    accessible: Mapped[bool | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "uq_onboarding_steps_one_unanswered_per_run",
    OnboardingStep.run_id,
    unique=True,
    postgresql_where=text("answered_at IS NULL"),
)
