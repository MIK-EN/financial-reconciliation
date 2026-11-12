from collections.abc import Iterator

import pytest


@pytest.fixture
def client() -> Iterator[object]:
    from english_for_developers.app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(), base_url="http://testserver") as test_client:
        yield test_client
