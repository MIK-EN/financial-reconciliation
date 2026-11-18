import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from english_for_developers.api.request_logging import HANDLER_NAME, configure_request_logging
from english_for_developers.app import create_app

LOGGER_NAME = "english_for_developers.request"


class _ValidationPayload(BaseModel):
    name: str


def _echo_payload(payload: _ValidationPayload) -> _ValidationPayload:
    return payload


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]


def test_unknown_path_is_logged_without_leaking_raw_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with TestClient(create_app(), base_url="http://testserver") as client:
        response = client.get("/api/v1/definitely-not-here/secret-token-123")

    assert response.status_code == 404
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "route=unmatched" in messages[0]
    assert "status=404" in messages[0]
    assert "secret-token-123" not in messages[0]
    assert "secret-token-123" not in caplog.text


def test_oversized_json_body_is_logged_as_request_too_large(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    oversized = b'{"padding":"' + (b"x" * (16 * 1024)) + b'"}'

    with TestClient(create_app(), base_url="http://testserver") as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Content-Type": "application/json"},
            content=oversized,
        )

    assert response.status_code == 413
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "status=413" in messages[0]
    assert "error_code=request_too_large" in messages[0]


def test_credentials_cookies_and_csrf_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with TestClient(create_app(), base_url="http://testserver") as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://testserver",
                "Cookie": "eds_session_dev=SUPERSECRET",
                "X-CSRF-Token": "CSRFSECRET",
            },
            json={"username": "u", "password": "PASSWORD-VALUE-xyz"},
        )

    request_id = response.headers["x-request-id"]
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "route=/api/v1/auth/login" in messages[0]
    assert f"request_id={request_id}" in messages[0]
    for secret in ("SUPERSECRET", "CSRFSECRET", "PASSWORD-VALUE-xyz"):
        assert secret not in messages[0]
        assert secret not in caplog.text


def test_validation_error_is_logged_with_stable_code(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    app = create_app()
    app.add_api_route("/__validate", _echo_payload, methods=["POST"])

    with TestClient(app, base_url="http://testserver") as client:
        response = client.post("/__validate", json={})

    assert response.status_code == 422
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "route=/__validate" in messages[0]
    assert "status=422" in messages[0]
    assert "error_code=validation_error" in messages[0]


def test_unhandled_exception_is_logged_as_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    app = create_app()
    app.add_api_route("/__boom", lambda: 1 / 0)

    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as client:
        response = client.get("/__boom")

    assert response.status_code == 500
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "route=/__boom" in messages[0]
    assert "status=500" in messages[0]
    assert "error_code=internal_error" in messages[0]
    assert "division by zero" not in messages[0]


def test_query_string_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    with TestClient(create_app(), base_url="http://testserver") as client:
        response = client.get("/api/v1/context?token=ABC123")

    assert response.status_code in {200, 503}
    messages = _messages(caplog)
    assert len(messages) == 1
    assert "ABC123" not in messages[0]
    assert "ABC123" not in caplog.text


def _named_request_log_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger(LOGGER_NAME).handlers
        if handler.name == HANDLER_NAME
    ]


@pytest.fixture
def clean_request_log_handlers() -> Iterator[None]:
    logger = logging.getLogger(LOGGER_NAME)

    def remove_named_handlers() -> None:
        for handler in _named_request_log_handlers():
            logger.removeHandler(handler)

    remove_named_handlers()
    yield
    remove_named_handlers()


def test_configure_request_logging_attaches_one_handler(clean_request_log_handlers: None) -> None:
    configure_request_logging()
    configure_request_logging()
    configure_request_logging()

    assert len(_named_request_log_handlers()) == 1


def test_request_line_is_written_to_stdout(
    clean_request_log_handlers: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app()

    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/nope")

    captured = capsys.readouterr().out
    assert response.status_code == 404
    assert "request request_id=" in captured
    assert "status=404" in captured
    assert "/nope" not in captured
