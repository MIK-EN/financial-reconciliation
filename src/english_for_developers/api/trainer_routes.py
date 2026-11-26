"""Public read-only trainer content, independent of accounts and guest sessions."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.api.dependencies import get_db
from english_for_developers.api.errors import ApiError
from english_for_developers.storage.models import TrainerBundle, TrainerSettings
from english_for_developers.trainer.content import TrainerContent

router = APIRouter(prefix="/api/v1/trainer", tags=["trainer"])


class TrainerResponse(BaseModel):
    content: TrainerContent
    content_hash: str


@router.get("", response_model=TrainerResponse)
def get_trainer(session: Session = Depends(get_db)) -> TrainerResponse:  # noqa: B008
    # One statement avoids mixing the setting and bundle during a publication.
    bundle = session.scalar(
        select(TrainerBundle).join(
            TrainerSettings, TrainerSettings.active_version == TrainerBundle.version
        )
    )
    if bundle is None:
        raise ApiError(503, "trainer_unavailable", "Trainer content has not been published")
    return TrainerResponse(
        content=TrainerContent.model_validate(bundle.content_json), content_hash=bundle.content_hash
    )
