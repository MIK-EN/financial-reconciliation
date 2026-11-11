import copy
import json
from dataclasses import replace

import pytest

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.models import ContentBundle as StoredBundle
from english_for_developers.storage.models import ContentSettings


class MemorySession:
    def __init__(self) -> None:
        self.bundles: dict[str, StoredBundle] = {}
        self.settings: ContentSettings | None = None

    def get(self, model: type[object], key: object) -> object | None:
        if model is StoredBundle:
            return self.bundles.get(str(key))
        if model is ContentSettings and key == 1:
            return self.settings
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, instance: object) -> None:
        if isinstance(instance, StoredBundle):
            self.bundles[instance.version] = instance
        elif isinstance(instance, ContentSettings):
            self.settings = instance
        else:
            raise AssertionError(f"Unexpected instance: {instance}")

    def flush(self) -> None:
        pass


def test_first_import_stores_the_exact_validated_document_and_activates(bundle) -> None:
    session = MemorySession()

    result = import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]

    stored = session.bundles[bundle.bundle_version]
    assert stored.content_hash == bundle.content_hash
    assert stored.content_json == json.loads(bundle.canonical_json)
    assert session.settings is not None
    assert session.settings.id == 1
    assert session.settings.active_version == bundle.bundle_version
    assert session.settings.threshold_percent == 20
    assert result.inserted and result.activated


def test_repeat_import_of_same_version_and_hash_is_unchanged(bundle) -> None:
    session = MemorySession()
    import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]
    stored = session.bundles[bundle.bundle_version]

    result = import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]

    assert session.bundles[bundle.bundle_version] is stored
    assert not result.inserted and not result.activated


def test_same_version_with_different_content_is_rejected(bundle, raw_bundle) -> None:
    session = MemorySession()
    import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]
    changed_raw = copy.deepcopy(raw_bundle)
    changed_raw["recommendations"][0]["description"] += " Updated."
    changed_bundle = validate_bundle(changed_raw)

    with pytest.raises(ValueError, match="immutable"):
        import_bundle(session, changed_bundle, activate=True, threshold_percent=30)  # type: ignore[arg-type]

    assert session.settings is not None
    assert session.settings.threshold_percent == 20


def test_bundle_with_a_forged_hash_is_rejected_without_publication(bundle) -> None:
    session = MemorySession()

    with pytest.raises(ValueError, match="hash"):
        import_bundle(
            session,
            replace(bundle, content_hash="0" * 64),
            activate=True,
            threshold_percent=20,
        )  # type: ignore[arg-type]

    assert session.bundles == {}
    assert session.settings is None


def test_new_content_version_can_be_activated_without_mutating_the_old_bundle(
    bundle, raw_bundle
) -> None:
    session = MemorySession()
    import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]
    old_json = copy.deepcopy(session.bundles[bundle.bundle_version].content_json)
    next_raw = copy.deepcopy(raw_bundle)
    next_raw["bundle_version"] = "onboarding-v2"
    next_bundle = validate_bundle(next_raw)

    result = import_bundle(session, next_bundle, activate=True, threshold_percent=30)  # type: ignore[arg-type]

    assert session.settings is not None
    assert session.settings.active_version == "onboarding-v2"
    assert session.settings.threshold_percent == 30
    assert session.bundles[bundle.bundle_version].content_json == old_json
    assert result.inserted and result.activated


def test_inactive_import_does_not_change_the_active_bundle(bundle, raw_bundle) -> None:
    session = MemorySession()
    import_bundle(session, bundle, activate=True, threshold_percent=20)  # type: ignore[arg-type]
    next_raw = copy.deepcopy(raw_bundle)
    next_raw["bundle_version"] = "onboarding-v2"
    next_bundle = validate_bundle(next_raw)

    result = import_bundle(session, next_bundle, activate=False, threshold_percent=30)  # type: ignore[arg-type]

    assert session.settings is not None
    assert session.settings.active_version == bundle.bundle_version
    assert session.settings.threshold_percent == 20
    assert result.inserted and not result.activated


@pytest.mark.parametrize("threshold", [-1, 101, True, 20.0])
def test_invalid_threshold_is_rejected_before_any_change(bundle, threshold) -> None:
    session = MemorySession()

    with pytest.raises(ValueError, match="integer from 0 to 100"):
        import_bundle(
            session,
            bundle,
            activate=True,
            threshold_percent=threshold,  # type: ignore[arg-type]
        )

    assert session.bundles == {}
    assert session.settings is None
