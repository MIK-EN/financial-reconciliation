from collections.abc import Iterator

import pytest


class FakeSession:
    def __init__(self) -> None:
        self.record = None

    def scalar(self, _statement):
        return self.record

    def add(self, record) -> None:
        self.record = record

    def commit(self) -> None:
        return None


@pytest.fixture
def client() -> Iterator[object]:
    from fastapi.testclient import TestClient

    from english_for_developers.api.dependencies import get_db
    from english_for_developers.app import create_app

    fake_session = FakeSession()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fake_session
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
