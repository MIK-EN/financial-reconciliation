import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.models import (
    BrowserSession,
    ContentBundle,
    ContentSettings,
    OnboardingRun,
    OnboardingStep,
)


class FakeSession:
    def __init__(self) -> None:
        raw_bundle = json.loads(
            (Path(__file__).parents[2] / "content" / "onboarding-v1.json").read_text()
        )
        bundle = validate_bundle(raw_bundle)
        self.browser_session: BrowserSession | None = None
        self.run: OnboardingRun | None = None
        self.steps: dict[object, OnboardingStep] = {}
        self.bundle = ContentBundle(
            version=bundle.bundle_version,
            content_hash=bundle.content_hash,
            normalization_version=bundle.normalization_version,
            policy_version=bundle.policy_version,
            content_json=raw_bundle,
            created_at=datetime.now(UTC),
        )
        self.settings = ContentSettings(
            id=1, active_version=bundle.bundle_version, threshold_percent=20
        )

    def scalar(self, statement):
        model = statement.column_descriptions[0].get("entity")
        if model is BrowserSession:
            return self.browser_session
        if model is OnboardingRun:
            return self.run
        if model is OnboardingStep:
            values = set(statement.compile().params.values())
            return next(
                (
                    step
                    for step in self.steps.values()
                    if step.id in values and step.run_id in values
                ),
                None,
            )
        raise AssertionError(f"Unexpected scalar model: {model}")

    def get(self, model, key):
        if model is ContentSettings and key == 1:
            return self.settings
        if model is ContentBundle and key == self.bundle.version:
            return self.bundle
        if model is OnboardingStep:
            return self.steps.get(key)
        return None

    def add(self, record) -> None:
        if isinstance(record, BrowserSession):
            self.browser_session = record
        elif isinstance(record, OnboardingRun):
            self.run = record
        elif isinstance(record, OnboardingStep):
            self.steps[record.id] = record
        else:
            raise AssertionError(f"Unexpected record: {record}")

    def commit(self) -> None:
        return None


@pytest.fixture
def app():
    from english_for_developers.app import create_app

    fake_session = FakeSession()
    application = create_app()
    from english_for_developers.api.dependencies import get_db

    application.dependency_overrides[get_db] = lambda: fake_session
    return application


@pytest.fixture
def client(app) -> Iterator[object]:
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
