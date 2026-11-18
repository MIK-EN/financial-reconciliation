from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from english_for_developers.storage.cleanup import (
    RETENTION_AFTER_EXPIRY,
    CleanupResult,
    cleanup_expired_sessions,
)
from english_for_developers.storage.models import (
    BrowserSession,
    ContentBundle,
    ContentSettings,
    OnboardingRun,
    OnboardingStep,
    User,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)
CUTOFF = NOW - RETENTION_AFTER_EXPIRY


def _add_bundle(session: Session, version: str = "cleanup-test-v1") -> ContentBundle:
    bundle = ContentBundle(
        version=version,
        content_hash=uuid4().hex + uuid4().hex,
        normalization_version="surface-v1",
        policy_version="routing-v1",
        content_json={"test": True},
        created_at=NOW,
    )
    session.add(bundle)
    session.flush()
    return bundle


def _add_session(
    session: Session,
    *,
    expires_at: datetime,
    kind: str = "anonymous",
    user: User | None = None,
    revoked_at: datetime | None = None,
) -> BrowserSession:
    browser_session = BrowserSession(
        id=uuid4(),
        kind=kind,
        token_hash=uuid4().hex + uuid4().hex,
        user_id=None if user is None else user.id,
        csrf_secret="csrf-secret",
        created_at=NOW - timedelta(days=100),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    session.add(browser_session)
    session.flush()
    return browser_session


def _add_user(session: Session, username: str = "reader") -> User:
    user = User(
        id=uuid4(),
        username=username,
        password_hash="unused",
        created_at=NOW - timedelta(days=100),
    )
    session.add(user)
    session.flush()
    return user


def _add_run(
    session: Session,
    *,
    browser_session: BrowserSession,
    bundle: ContentBundle,
    expires_at: datetime,
    steps: int = 2,
    user: User | None = None,
    claimed_at: datetime | None = None,
) -> tuple[OnboardingRun, list[OnboardingStep]]:
    claimed = user is not None
    run = OnboardingRun(
        id=uuid4(),
        anonymous_session_id=browser_session.id,
        user_id=None if user is None else user.id,
        content_version=bundle.version,
        normalization_version=bundle.normalization_version,
        policy_version=bundle.policy_version,
        threshold_percent=20,
        status="completed" if claimed else "active",
        current_step_id=None,
        recommended_level="foundations" if claimed else None,
        selected_level="foundations" if claimed else None,
        reason_code="start_accessible" if claimed else None,
        revision=1 if claimed else 0,
        created_at=NOW - timedelta(days=100),
        completed_at=NOW - timedelta(days=100) if claimed else None,
        claimed_at=claimed_at,
        expires_at=expires_at,
    )
    session.add(run)
    session.flush()
    created: list[OnboardingStep] = []
    for ordinal in range(1, steps + 1):
        answered = ordinal < steps
        step = OnboardingStep(
            id=uuid4(),
            run_id=run.id,
            ordinal=ordinal,
            text_id=f"text-{ordinal}",
            created_at=NOW - timedelta(days=100),
            answer_mode="all_known" if answered else None,
            unknown_word_ids=[] if answered else None,
            unknown_count=0 if answered else None,
            total_word_count=8 if answered else None,
            accessible=True if answered else None,
            answered_at=NOW - timedelta(days=100) if answered else None,
        )
        session.add(step)
        created.append(step)
    session.flush()
    if user is not None:
        user.current_run_id = run.id
        session.flush()
    return run, created


def _ids(session: Session, model: type[Any]) -> set[Any]:
    primary_key = model.__mapper__.primary_key[0]
    return set(session.scalars(select(primary_key)))


def _counts(session: Session) -> dict[str, int]:
    return {
        "bundles": session.scalar(select(func.count()).select_from(ContentBundle)) or 0,
        "settings": session.scalar(select(func.count()).select_from(ContentSettings)) or 0,
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "runs": session.scalar(select(func.count()).select_from(OnboardingRun)) or 0,
        "steps": session.scalar(select(func.count()).select_from(OnboardingStep)) or 0,
        "sessions": session.scalar(select(func.count()).select_from(BrowserSession)) or 0,
    }


def _snapshot(session: Session) -> dict[str, object]:
    settings = session.get(ContentSettings, 1)
    return {
        "bundles": _ids(session, ContentBundle),
        "settings": None
        if settings is None
        else (settings.active_version, settings.threshold_percent),
        "users": _ids(session, User),
        "runs": _ids(session, OnboardingRun),
        "steps": _ids(session, OnboardingStep),
        "sessions": _ids(session, BrowserSession),
    }


def test_run_expiring_exactly_at_retention_cutoff_is_kept(db_session: Session) -> None:
    bundle = _add_bundle(db_session)
    browser_session = _add_session(db_session, expires_at=CUTOFF)
    run, steps = _add_run(
        db_session, browser_session=browser_session, bundle=bundle, expires_at=CUTOFF
    )

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=0, steps=0, sessions=0)
    assert _ids(db_session, OnboardingRun) == {run.id}
    assert _ids(db_session, OnboardingStep) == {step.id for step in steps}
    assert _ids(db_session, BrowserSession) == {browser_session.id}


def test_run_older_than_retention_is_deleted_with_steps_and_session(
    db_session: Session,
) -> None:
    old_expiry = CUTOFF - timedelta(microseconds=1)
    bundle = _add_bundle(db_session)
    browser_session = _add_session(db_session, expires_at=old_expiry)
    run, steps = _add_run(
        db_session, browser_session=browser_session, bundle=bundle, expires_at=old_expiry
    )
    run.current_step_id = steps[-1].id
    db_session.flush()

    result = cleanup_expired_sessions(db_session, NOW)
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    assert result == CleanupResult(runs=1, steps=2, sessions=1)
    assert _ids(db_session, OnboardingRun) == set()
    assert _ids(db_session, OnboardingStep) == set()
    assert _ids(db_session, BrowserSession) == set()
    assert run.id not in _ids(db_session, OnboardingRun)
    assert {step.id for step in steps}.isdisjoint(_ids(db_session, OnboardingStep))


def test_claimed_run_user_session_and_bundle_survive(db_session: Session) -> None:
    bundle = _add_bundle(db_session)
    user = _add_user(db_session)
    browser_session = _add_session(
        db_session,
        expires_at=NOW - timedelta(days=120),
        revoked_at=NOW - timedelta(days=90),
    )
    run, steps = _add_run(
        db_session,
        browser_session=browser_session,
        bundle=bundle,
        expires_at=NOW - timedelta(days=90),
        user=user,
        claimed_at=NOW - timedelta(days=90),
    )

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=0, steps=0, sessions=0)
    assert _ids(db_session, OnboardingRun) == {run.id}
    assert _ids(db_session, OnboardingStep) == {step.id for step in steps}
    assert _ids(db_session, BrowserSession) == {browser_session.id}
    assert _ids(db_session, User) == {user.id}
    assert _ids(db_session, ContentBundle) == {bundle.version}
    db_session.expire_all()
    assert db_session.get(User, user.id).current_run_id == run.id  # type: ignore[union-attr]


def test_mixed_batch_deletes_only_expired_unclaimed_run(db_session: Session) -> None:
    bundle = _add_bundle(db_session)
    settings = ContentSettings(id=1, active_version=bundle.version, threshold_percent=20)
    db_session.add(settings)
    db_session.flush()

    deletable_session = _add_session(db_session, expires_at=CUTOFF - timedelta(microseconds=1))
    deletable_run, deletable_steps = _add_run(
        db_session,
        browser_session=deletable_session,
        bundle=bundle,
        expires_at=CUTOFF - timedelta(microseconds=1),
    )
    kept_session = _add_session(db_session, expires_at=CUTOFF)
    kept_run, kept_steps = _add_run(
        db_session, browser_session=kept_session, bundle=bundle, expires_at=CUTOFF
    )
    user = _add_user(db_session)
    claimed_session = _add_session(
        db_session,
        expires_at=NOW - timedelta(days=200),
        revoked_at=NOW - timedelta(days=150),
    )
    claimed_run, claimed_steps = _add_run(
        db_session,
        browser_session=claimed_session,
        bundle=bundle,
        expires_at=NOW - timedelta(days=150),
        user=user,
        claimed_at=NOW - timedelta(days=150),
    )
    assert _counts(db_session) == {
        "bundles": 1,
        "settings": 1,
        "users": 1,
        "runs": 3,
        "steps": 6,
        "sessions": 3,
    }

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=1, steps=2, sessions=1)
    assert _ids(db_session, OnboardingRun) == {kept_run.id, claimed_run.id}
    assert deletable_run.id not in _ids(db_session, OnboardingRun)
    assert _ids(db_session, OnboardingStep) == {step.id for step in [*kept_steps, *claimed_steps]}
    assert {step.id for step in deletable_steps}.isdisjoint(_ids(db_session, OnboardingStep))
    assert _ids(db_session, BrowserSession) == {kept_session.id, claimed_session.id}
    assert _ids(db_session, User) == {user.id}
    assert _counts(db_session) == {
        "bundles": 1,
        "settings": 1,
        "users": 1,
        "runs": 2,
        "steps": 4,
        "sessions": 2,
    }


def test_second_cleanup_is_a_noop(db_session: Session) -> None:
    bundle = _add_bundle(db_session)
    browser_session = _add_session(db_session, expires_at=CUTOFF - timedelta(microseconds=1))
    _add_run(
        db_session,
        browser_session=browser_session,
        bundle=bundle,
        expires_at=CUTOFF - timedelta(microseconds=1),
    )
    kept_session = _add_session(db_session, expires_at=CUTOFF)
    _add_run(db_session, browser_session=kept_session, bundle=bundle, expires_at=CUTOFF)

    first = cleanup_expired_sessions(db_session, NOW)
    after_first = _snapshot(db_session)
    second = cleanup_expired_sessions(db_session, NOW)

    assert first == CleanupResult(runs=1, steps=2, sessions=1)
    assert second == CleanupResult(runs=0, steps=0, sessions=0)
    assert _snapshot(db_session) == after_first
    assert _counts(db_session) == {
        "bundles": 1,
        "settings": 0,
        "users": 0,
        "runs": 1,
        "steps": 2,
        "sessions": 1,
    }


def test_orphan_anonymous_sessions_are_deleted_only_after_retention(
    db_session: Session,
) -> None:
    old_orphan = _add_session(db_session, expires_at=CUTOFF - timedelta(microseconds=1))
    recent_orphan = _add_session(db_session, expires_at=NOW - timedelta(days=10))

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=0, steps=0, sessions=1)
    assert _ids(db_session, BrowserSession) == {recent_orphan.id}
    assert old_orphan.id not in _ids(db_session, BrowserSession)


def test_old_authenticated_session_is_deleted_but_user_remains(
    db_session: Session,
) -> None:
    user = _add_user(db_session)
    authenticated = _add_session(
        db_session,
        kind="authenticated",
        user=user,
        expires_at=CUTOFF - timedelta(days=1),
        revoked_at=NOW - timedelta(days=45),
    )

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=0, steps=0, sessions=1)
    assert _ids(db_session, BrowserSession) == set()
    assert authenticated.id not in _ids(db_session, BrowserSession)
    assert _ids(db_session, User) == {user.id}


def test_bundle_referenced_by_a_deleted_run_remains(db_session: Session) -> None:
    bundle = _add_bundle(db_session)
    browser_session = _add_session(db_session, expires_at=CUTOFF - timedelta(microseconds=1))
    _add_run(
        db_session,
        browser_session=browser_session,
        bundle=bundle,
        expires_at=CUTOFF - timedelta(microseconds=1),
    )

    result = cleanup_expired_sessions(db_session, NOW)

    assert result == CleanupResult(runs=1, steps=2, sessions=1)
    assert _ids(db_session, OnboardingRun) == set()
    assert _ids(db_session, ContentBundle) == {bundle.version}
    db_session.expire_all()
    stored = db_session.get(ContentBundle, bundle.version)
    assert stored is not None and stored.content_hash == bundle.content_hash
