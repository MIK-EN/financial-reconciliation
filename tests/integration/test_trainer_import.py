import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from english_for_developers.app import create_app
from english_for_developers.cli import main
from english_for_developers.storage.models import TrainerBundle, TrainerSettings
from english_for_developers.trainer.content import TrainerContent
from english_for_developers.trainer.importer import import_trainer

CONTENT = Path(__file__).parents[2] / "content" / "trainer-v1.json"


def test_import_repeat_conflict_and_activation(db_session):
    raw = json.loads(CONTENT.read_text())
    content = TrainerContent.model_validate(raw)
    assert import_trainer(db_session, content, activate=True).inserted
    assert not import_trainer(db_session, content, activate=True).inserted
    assert db_session.get(TrainerSettings, 1).active_version == content.version
    raw["topics"][0]["description"] = "Другой текст"
    with pytest.raises(ValueError, match="immutable"):
        import_trainer(db_session, TrainerContent.model_validate(raw), activate=True)
    assert db_session.get(TrainerBundle, content.version).content_hash == content.content_hash
    raw["version"] = "trainer-v2"
    newer = TrainerContent.model_validate(raw)
    import_trainer(db_session, newer, activate=False)
    db_session.expire_all()
    assert db_session.get(TrainerSettings, 1).active_version == content.version
    import_trainer(db_session, newer, activate=True)
    db_session.expire_all()
    assert db_session.get(TrainerSettings, 1).active_version == newer.version
    assert db_session.scalar(select(func.count()).select_from(TrainerBundle)) == 2


def test_cli_commits_and_public_http_serves_imported_content(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/trainer").status_code == 503
        assert main(["trainer", "import", str(CONTENT)]) == 0
        assert client.get("/api/v1/trainer").status_code == 503
        assert main(["trainer", "import", str(CONTENT), "--activate"]) == 0
        response = client.get("/api/v1/trainer")
    assert response.status_code == 200
    assert response.json()["content"] == json.loads(CONTENT.read_text())
    assert len(response.json()["content_hash"]) == 64


def test_import_and_activation_roll_back_together(test_engine):
    from sqlalchemy.orm import Session

    content = TrainerContent.model_validate_json(CONTENT.read_text())
    with Session(test_engine) as session:
        import_trainer(session, content, activate=True)
        session.rollback()
    with Session(test_engine) as session:
        assert session.get(TrainerBundle, content.version) is None
        assert session.get(TrainerSettings, 1) is None
