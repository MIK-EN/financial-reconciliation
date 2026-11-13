"""Allow an unanswered onboarding step.

Revision ID: 0002_unanswered_step
Revises: 0001_onboarding
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_unanswered_step"
down_revision: str | Sequence[str] | None = "0001_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONDITION = (
    "(answer_mode IS NULL AND unknown_word_ids IS NULL AND unknown_count IS NULL "
    "AND total_word_count IS NULL AND accessible IS NULL AND answered_at IS NULL) "
    "OR (answer_mode IN ('all_known', 'unknown_words') "
    "AND unknown_word_ids IS NOT NULL AND unknown_count IS NOT NULL "
    "AND total_word_count IS NOT NULL AND accessible IS NOT NULL "
    "AND answered_at IS NOT NULL AND jsonb_typeof(unknown_word_ids) = 'array' "
    "AND jsonb_array_length(unknown_word_ids) = unknown_count "
    "AND unknown_count BETWEEN 0 AND total_word_count AND total_word_count > 0 "
    "AND ((answer_mode = 'all_known' AND unknown_count = 0) OR "
    "(answer_mode = 'unknown_words' AND unknown_count > 0)))"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE onboarding_steps DROP CONSTRAINT "
        "ck_onboarding_steps_ck_onboarding_steps_answer_consistency"
    )
    op.execute(
        "ALTER TABLE onboarding_steps ADD CONSTRAINT "
        "ck_onboarding_steps_ck_onboarding_steps_answer_consistency CHECK (" + _CONDITION + ")"
    )


def downgrade() -> None:
    upgrade()
