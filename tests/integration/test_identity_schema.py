from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from english_for_developers.storage.models import User


def _add_password_user(db_session: Session) -> UUID:
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            username=user_id.hex,
            password_hash="test-password-hash",
            created_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    return user_id


def _add_identity(
    db_session: Session, user_id: UUID, *, provider: str = "telegram", subject: str = "123"
) -> None:
    from english_for_developers.storage import models

    db_session.add(
        models.AuthIdentity(
            id=uuid4(),
            user_id=user_id,
            provider=provider,
            subject=subject,
            created_at=datetime.now(UTC),
        )
    )


def _insert_browser_session(
    db_session: Session,
    *,
    nonce_hash: str | None,
    nonce_expires_at: datetime | None,
    user_id: UUID | None = None,
) -> None:
    now = datetime.now(UTC)
    db_session.execute(
        text(
            """
            INSERT INTO browser_sessions (
                id, kind, token_hash, user_id, csrf_secret, created_at, expires_at,
                telegram_nonce_hash, telegram_nonce_expires_at
            ) VALUES (
                :id, :kind, :token_hash, :user_id, :csrf_secret, :created_at, :expires_at,
                :nonce_hash, :nonce_expires_at
            )
            """
        ),
        {
            "id": uuid4(),
            "kind": "anonymous" if user_id is None else "authenticated",
            "token_hash": "a" * 64,
            "user_id": user_id,
            "csrf_secret": "test-csrf-secret",
            "created_at": now,
            "expires_at": now + timedelta(days=7),
            "nonce_hash": nonce_hash,
            "nonce_expires_at": nonce_expires_at,
        },
    )


def test_user_can_be_created_without_password_credentials(db_session: Session) -> None:
    db_session.add(
        User(id=uuid4(), username=None, password_hash=None, created_at=datetime.now(UTC))
    )
    db_session.flush()


@pytest.mark.parametrize(
    ("username", "password_hash"),
    [("reader", None), (None, "test-password-hash")],
    ids=["username-only", "password-hash-only"],
)
def test_user_credentials_must_be_set_as_a_pair(
    db_session: Session, username: str | None, password_hash: str | None
) -> None:
    db_session.add(
        User(
            id=uuid4(), username=username, password_hash=password_hash, created_at=datetime.now(UTC)
        )
    )
    with pytest.raises(IntegrityError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "ck_users_credentials_pair"


def test_multiple_users_can_have_null_usernames(db_session: Session) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            User(id=uuid4(), username=None, password_hash=None, created_at=now),
            User(id=uuid4(), username=None, password_hash=None, created_at=now),
        ]
    )
    db_session.flush()


def test_telegram_identity_can_be_created_for_a_user(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id)
    db_session.flush()


def test_telegram_subject_cannot_be_shared_by_two_users(db_session: Session) -> None:
    first_user_id = _add_password_user(db_session)
    second_user_id = _add_password_user(db_session)
    _add_identity(db_session, first_user_id)
    db_session.flush()
    _add_identity(db_session, second_user_id)
    with pytest.raises(IntegrityError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "uq_auth_identities_provider_subject"


def test_user_can_have_multiple_telegram_identities(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id)
    db_session.flush()
    _add_identity(db_session, user_id, subject="124")
    db_session.flush()


def test_identity_provider_must_be_telegram(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id, provider="google")
    with pytest.raises(IntegrityError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "ck_auth_identities_provider_valid"


def test_identity_subject_cannot_be_empty(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id, subject="")
    with pytest.raises(IntegrityError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "ck_auth_identities_subject_not_empty"


def test_identity_subject_is_limited_to_128_characters(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id, subject="1" * 128)
    db_session.flush()
    _add_identity(db_session, user_id, subject="1" * 129)
    with pytest.raises(DBAPIError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.sqlstate == "22001"


def test_identity_requires_an_existing_user(db_session: Session) -> None:
    _add_identity(db_session, uuid4())
    with pytest.raises(IntegrityError) as exc:
        db_session.flush()
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "fk_auth_identities_user_id_users"


def test_user_with_an_identity_cannot_be_deleted(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    _add_identity(db_session, user_id)
    db_session.flush()
    with pytest.raises(IntegrityError) as exc:
        db_session.execute(delete(User.__table__).where(User.__table__.c.id == user_id))
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "fk_auth_identities_user_id_users"


def test_anonymous_session_can_have_a_telegram_nonce(db_session: Session) -> None:
    _insert_browser_session(
        db_session, nonce_hash="b" * 64, nonce_expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )


@pytest.mark.parametrize(
    ("nonce_hash", "has_expiry"),
    [("b" * 64, False), (None, True), ("b" * 63, True)],
    ids=["hash-only", "expiry-only", "short-hash"],
)
def test_anonymous_session_rejects_invalid_telegram_nonce(
    db_session: Session, nonce_hash: str | None, has_expiry: bool
) -> None:
    nonce_expires_at = datetime.now(UTC) + timedelta(minutes=5) if has_expiry else None
    with pytest.raises(IntegrityError) as exc:
        _insert_browser_session(
            db_session, nonce_hash=nonce_hash, nonce_expires_at=nonce_expires_at
        )
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "ck_browser_sessions_telegram_nonce_valid"


def test_authenticated_session_cannot_have_a_telegram_nonce(db_session: Session) -> None:
    user_id = _add_password_user(db_session)
    with pytest.raises(IntegrityError) as exc:
        _insert_browser_session(
            db_session,
            nonce_hash="b" * 64,
            nonce_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            user_id=user_id,
        )
    db_session.rollback()
    assert exc.value.orig.diag.constraint_name == "ck_browser_sessions_telegram_nonce_valid"
