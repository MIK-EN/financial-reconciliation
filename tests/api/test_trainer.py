import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from english_for_developers.api.dependencies import get_db
from english_for_developers.app import create_app
from english_for_developers.storage.models import TrainerBundle
from english_for_developers.trainer.content import TrainerContent


@pytest.mark.parametrize("state", ["ready", "unpublished", "unavailable"])
def test_public_trainer_api_without_accounts_or_cookies(state):
    raw = json.loads((Path(__file__).parents[2] / "content" / "trainer-v1.json").read_text())
    content = TrainerContent.model_validate(raw)

    class Session:
        def scalar(self, statement):
            if state == "unavailable":
                raise OperationalError("select", {}, Exception("private-db-details"))
            if state == "unpublished":
                return None
            return TrainerBundle(
                version=content.version,
                content_hash=content.content_hash,
                content_json=raw,
                created_at=datetime.now(UTC),
            )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: Session()
    with TestClient(app) as client:
        response = client.get("/api/v1/trainer")
    assert "set-cookie" not in response.headers
    assert response.headers["X-Request-ID"]
    if state == "ready":
        assert response.status_code == 200
        assert response.json() == {"content": raw, "content_hash": content.content_hash}
    else:
        assert response.status_code == 503
        expected = "trainer_unavailable" if state == "unpublished" else "database_unavailable"
        assert response.json()["code"] == expected
        assert "private-db-details" not in response.text
