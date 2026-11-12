"""Store and publish immutable, validated onboarding content bundles."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from english_for_developers.content.schema import ContentBundle as ValidatedBundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.models import ContentBundle, ContentSettings


@dataclass(frozen=True)
class ImportResult:
    version: str
    content_hash: str
    inserted: bool
    activated: bool


def import_bundle(
    session: Session,
    bundle: ValidatedBundle,
    *,
    activate: bool,
    threshold_percent: int,
) -> ImportResult:
    """Insert an immutable bundle and optionally select it for future runs.

    The caller owns the transaction and must commit or roll it back as one unit.
    """
    if type(threshold_percent) is not int or not 0 <= threshold_percent <= 100:
        raise ValueError("threshold_percent must be an integer from 0 to 100")
    if type(activate) is not bool:
        raise ValueError("activate must be a boolean")

    try:
        raw_content = json.loads(bundle.canonical_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Bundle canonical JSON is invalid") from error
    verified = validate_bundle(raw_content)
    if verified != bundle:
        raise ValueError("Bundle content hash or validated snapshot does not match")

    existing = session.get(ContentBundle, bundle.bundle_version)
    inserted = existing is None
    if existing is not None:
        if existing.content_hash != bundle.content_hash or existing.content_json != raw_content:
            raise ValueError("A bundle version is immutable and already contains other content")
    else:
        session.add(
            ContentBundle(
                version=bundle.bundle_version,
                content_hash=bundle.content_hash,
                normalization_version=bundle.normalization_version,
                policy_version=bundle.policy_version,
                content_json=raw_content,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()

    activated = False
    if activate:
        settings = session.get(ContentSettings, 1)
        if settings is None:
            session.add(
                ContentSettings(
                    id=1,
                    active_version=bundle.bundle_version,
                    threshold_percent=threshold_percent,
                )
            )
            activated = True
        elif (
            settings.active_version != bundle.bundle_version
            or settings.threshold_percent != threshold_percent
        ):
            settings.active_version = bundle.bundle_version
            settings.threshold_percent = threshold_percent
            activated = True
        if activated:
            session.flush()

    return ImportResult(bundle.bundle_version, bundle.content_hash, inserted, activated)
