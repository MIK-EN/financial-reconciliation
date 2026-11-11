import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from english_for_developers.cli import main as cli_main
from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.models import (
    BrowserSession,
    ContentSettings,
    OnboardingRun,
)
from english_for_developers.storage.models import ContentBundle as StoredBundle

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def _bundle(version: str = "onboarding-v1"):
    raw = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    raw["bundle_version"] = version
    return validate_bundle(raw)


def test_first_import_persists_and_activates_valid_bundle(db_session: Session) -> None:
    bundle = _bundle()

    result = import_bundle(db_session, bundle, activate=True, threshold_percent=20)

    stored = db_session.get(StoredBundle, bundle.bundle_version)
    settings = db_session.get(ContentSettings, 1)
    assert stored is not None
    assert stored.content_hash == bundle.content_hash
    assert stored.content_json == json.loads(bundle.canonical_json)
    assert settings is not None
    assert settings.active_version == bundle.bundle_version
    assert settings.threshold_percent == 20
    assert result.inserted and result.activated


def test_same_version_and_hash_can_be_imported_repeatedly(db_session: Session) -> None:
    bundle = _bundle()
    first = import_bundle(db_session, bundle, activate=True, threshold_percent=20)
    second = import_bundle(db_session, bundle, activate=True, threshold_percent=20)

    assert first.inserted and first.activated
    assert not second.inserted and not second.activated
    assert (
        len(
            db_session.scalars(
                select(StoredBundle).where(StoredBundle.version == bundle.bundle_version)
            ).all()
        )
        == 1
    )


def test_changed_content_cannot_replace_an_existing_version(db_session: Session) -> None:
    original = _bundle()
    import_bundle(db_session, original, activate=True, threshold_percent=20)
    changed_raw = json.loads(original.canonical_json)
    changed_raw["recommendations"][0]["description"] += " Changed."

    with pytest.raises(ValueError, match="immutable"):
        import_bundle(db_session, validate_bundle(changed_raw), activate=True, threshold_percent=30)

    settings = db_session.get(ContentSettings, 1)
    stored = db_session.get(StoredBundle, original.bundle_version)
    assert settings is not None and settings.threshold_percent == 20
    assert stored is not None and stored.content_hash == original.content_hash


def test_new_activation_does_not_rewrite_existing_run_versions_or_threshold(
    db_session: Session,
) -> None:
    original = _bundle()
    import_bundle(db_session, original, activate=True, threshold_percent=20)
    now = datetime.now(UTC)
    browser_session = BrowserSession(
        id=uuid4(),
        kind="anonymous",
        token_hash=uuid4().hex + uuid4().hex,
        csrf_secret="csrf-secret",
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    run = OnboardingRun(
        id=uuid4(),
        anonymous_session_id=browser_session.id,
        user_id=None,
        content_version=original.bundle_version,
        normalization_version=original.normalization_version,
        policy_version=original.policy_version,
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
    db_session.add_all([browser_session, run])
    db_session.flush()
    newer = _bundle("onboarding-v2")

    import_bundle(db_session, newer, activate=True, threshold_percent=30)

    db_session.refresh(run)
    settings = db_session.get(ContentSettings, 1)
    assert run.content_version == "onboarding-v1"
    assert run.threshold_percent == 20
    assert settings is not None and settings.active_version == "onboarding-v2"
    assert settings.threshold_percent == 30


def test_content_in_use_by_a_run_cannot_be_deleted(db_session: Session) -> None:
    bundle = _bundle()
    import_bundle(db_session, bundle, activate=True, threshold_percent=20)
    now = datetime.now(UTC)
    browser_session = BrowserSession(
        id=uuid4(),
        kind="anonymous",
        token_hash=uuid4().hex + uuid4().hex,
        csrf_secret="csrf-secret",
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    run = OnboardingRun(
        id=uuid4(),
        anonymous_session_id=browser_session.id,
        user_id=None,
        content_version=bundle.bundle_version,
        normalization_version=bundle.normalization_version,
        policy_version=bundle.policy_version,
        threshold_percent=20,
        status="active",
        revision=0,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db_session.add_all([browser_session, run])
    db_session.flush()
    newer = _bundle("onboarding-v2")
    import_bundle(db_session, newer, activate=True, threshold_percent=20)
    stored = db_session.get(StoredBundle, bundle.bundle_version)
    assert stored is not None
    db_session.delete(stored)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cli_import_commits_one_atomic_publication(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    raw = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    raw["bundle_version"] = f"cli-{uuid4().hex}"
    content_path = tmp_path / "bundle.json"
    content_path.write_text(json.dumps(raw), encoding="utf-8")

    result = cli_main(
        [
            "content",
            "import",
            str(content_path),
            "--activate",
            "--threshold-percent",
            "20",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert f"stored {raw['bundle_version']} and activated" in output.out
    assert output.err == ""
