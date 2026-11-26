"""Publish validated trainer snapshots atomically; the caller owns the transaction."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from english_for_developers.content.importer import ImportResult
from english_for_developers.storage.models import TrainerBundle, TrainerSettings
from english_for_developers.trainer.content import TrainerContent


def import_trainer(session: Session, content: TrainerContent, *, activate: bool) -> ImportResult:
    # Revalidate even if a caller used Pydantic's unchecked model_construct.
    content = TrainerContent.model_validate(content.model_dump(mode="json"))
    raw = content.model_dump(mode="json")
    version = session.scalar(
        insert(TrainerBundle)
        .values(
            version=content.version,
            content_hash=content.content_hash,
            content_json=raw,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=[TrainerBundle.version])
        .returning(TrainerBundle.version)
    )
    stored = session.get(TrainerBundle, content.version)
    if stored is None or stored.content_hash != content.content_hash or stored.content_json != raw:
        raise ValueError("A trainer version is immutable; publish changes under a new version")
    if activate:
        session.execute(
            insert(TrainerSettings)
            .values(id=1, active_version=content.version)
            .on_conflict_do_update(
                index_elements=[TrainerSettings.id], set_={"active_version": content.version}
            )
        )
    return ImportResult(content.version, content.content_hash, version is not None, activate)
