from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from english_for_developers.storage.models import (
    Base,
    BrowserSession,
    ContentBundle,
    ContentSettings,
    OnboardingRun,
    OnboardingStep,
    User,
)

EXPECTED_TABLES = {
    "browser_sessions",
    "content_bundles",
    "content_settings",
    "onboarding_runs",
    "onboarding_steps",
    "users",
}


def test_migration_creates_the_six_product_tables(db_session: Session) -> None:
    database_tables = set(inspect(db_session.get_bind()).get_table_names())
    assert database_tables - {"alembic_version"} == EXPECTED_TABLES
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_required_unique_constraints_are_present(db_session: Session) -> None:
    inspector = inspect(db_session.get_bind())
    users = {item["name"] for item in inspector.get_unique_constraints("users")}
    sessions = {item["name"] for item in inspector.get_unique_constraints("browser_sessions")}
    runs = {item["name"] for item in inspector.get_unique_constraints("onboarding_runs")}
    assert "uq_users_username" in users
    assert "uq_browser_sessions_token_hash" in sessions
    assert "uq_onboarding_runs_anonymous_session_id" in runs
    step_indexes = {item["name"] for item in inspector.get_indexes("onboarding_steps")}
    user_foreign_keys = {item["name"] for item in inspector.get_foreign_keys("users")}
    assert "uq_onboarding_steps_one_unanswered_per_run" in step_indexes
    assert "fk_users_current_run_owned" in user_foreign_keys


def test_duplicate_username_is_rejected(db_session: Session) -> None:
    db_session.add_all(
        [
            User(
                id=uuid4(),
                username="reader",
                password_hash="hash-one",
                created_at=datetime.now(UTC),
            ),
            User(
                id=uuid4(),
                username="reader",
                password_hash="hash-two",
                created_at=datetime.now(UTC),
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_session_token_hash_is_rejected(db_session: Session) -> None:
    now = datetime.now(UTC)
    token_hash = "a" * 64
    db_session.add_all(
        [
            BrowserSession(
                id=uuid4(),
                kind="anonymous",
                token_hash=token_hash,
                csrf_secret="csrf-one",
                created_at=now,
                expires_at=now + timedelta(days=7),
            ),
            BrowserSession(
                id=uuid4(),
                kind="anonymous",
                token_hash=token_hash,
                csrf_secret="csrf-two",
                created_at=now,
                expires_at=now + timedelta(days=7),
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def _seed_active_run(db_session: Session) -> tuple[BrowserSession, OnboardingRun]:
    now = datetime.now(UTC)
    browser_session = BrowserSession(
        id=uuid4(),
        kind="anonymous",
        token_hash=uuid4().hex + uuid4().hex,
        csrf_secret="csrf-secret",
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    bundle = ContentBundle(
        version="onboarding-test-v1",
        content_hash="b" * 64,
        normalization_version="surface-v1",
        policy_version="routing-v1",
        content_json={"test": True},
        created_at=now,
    )
    db_session.add_all([browser_session, bundle])
    db_session.flush()
    db_session.add(ContentSettings(id=1, active_version=bundle.version, threshold_percent=20))
    run = OnboardingRun(
        id=uuid4(),
        anonymous_session_id=browser_session.id,
        user_id=None,
        content_version=bundle.version,
        normalization_version="surface-v1",
        policy_version="routing-v1",
        threshold_percent=20,
        status="active",
        current_step_id=None,
        recommended_level=None,
        selected_level=None,
        reason_code=None,
        revision=0,
        created_at=now,
        completed_at=None,
        claimed_at=None,
        expires_at=now + timedelta(days=7),
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        OnboardingStep(id=uuid4(), run_id=run.id, ordinal=1, text_id="start", created_at=now)
    )
    db_session.flush()
    return browser_session, run


def test_one_run_per_anonymous_session(db_session: Session) -> None:
    browser_session, run = _seed_active_run(db_session)
    db_session.add(
        OnboardingRun(
            id=uuid4(),
            anonymous_session_id=browser_session.id,
            user_id=None,
            content_version=run.content_version,
            normalization_version="surface-v1",
            policy_version="routing-v1",
            threshold_percent=20,
            status="active",
            revision=0,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_unanswered_step_per_run(db_session: Session) -> None:
    _, run = _seed_active_run(db_session)
    db_session.add(
        OnboardingStep(
            id=uuid4(),
            run_id=run.id,
            ordinal=2,
            text_id="installation",
            created_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("ordinal", [0, 5])
def test_step_ordinal_is_limited_to_one_through_four(db_session: Session, ordinal: int) -> None:
    _, run = _seed_active_run(db_session)
    now = datetime.now(UTC)
    db_session.add(
        OnboardingStep(
            id=uuid4(),
            run_id=run.id,
            ordinal=ordinal,
            text_id="installation",
            answer_mode="all_known",
            unknown_word_ids=[],
            unknown_count=0,
            total_word_count=8,
            accessible=True,
            answered_at=now,
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_text_cannot_repeat_in_one_run(db_session: Session) -> None:
    _, run = _seed_active_run(db_session)
    now = datetime.now(UTC)
    db_session.add(
        OnboardingStep(
            id=uuid4(),
            run_id=run.id,
            ordinal=2,
            text_id="start",
            answer_mode="all_known",
            unknown_word_ids=[],
            unknown_count=0,
            total_word_count=8,
            accessible=True,
            answered_at=now,
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_answer_fields_must_be_all_present_or_all_absent(db_session: Session) -> None:
    _, run = _seed_active_run(db_session)
    now = datetime.now(UTC)
    db_session.add(
        OnboardingStep(
            id=uuid4(),
            run_id=run.id,
            ordinal=2,
            text_id="installation",
            answer_mode="all_known",
            unknown_word_ids=None,
            unknown_count=None,
            total_word_count=None,
            accessible=None,
            answered_at=now,
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_current_run_must_belong_to_the_pointing_user(db_session: Session) -> None:
    _, run = _seed_active_run(db_session)
    owner = User(
        id=uuid4(), username="owner", password_hash="hash-owner", created_at=datetime.now(UTC)
    )
    other = User(
        id=uuid4(),
        username="other",
        password_hash="hash-other",
        current_run_id=run.id,
        created_at=datetime.now(UTC),
    )
    run.user_id = owner.id
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    run.claimed_at = datetime.now(UTC)
    run.recommended_level = "foundations"
    run.selected_level = "foundations"
    run.reason_code = "start_accessible"
    db_session.add_all([owner, other])
    with pytest.raises(IntegrityError):
        db_session.flush()
        db_session.execute(text("SET CONSTRAINTS fk_users_current_run_owned IMMEDIATE"))
