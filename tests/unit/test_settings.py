import pytest

from english_for_developers.settings import Settings


def test_telegram_client_id_is_trimmed_and_defaults_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_CLIENT_ID", " 42 ")
    assert Settings.from_env().telegram_client_id == "42"

    monkeypatch.delenv("TELEGRAM_CLIENT_ID", raising=False)
    assert Settings.from_env().telegram_client_id == ""
