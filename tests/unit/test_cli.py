import json
from datetime import UTC, datetime

import pytest

import english_for_developers.cli as cli
from english_for_developers.cli import main
from english_for_developers.storage.cleanup import CleanupResult


def test_content_validate_prints_version_and_hash(raw_bundle, tmp_path, capsys) -> None:
    content_path = tmp_path / "bundle.json"
    content_path.write_text(json.dumps(raw_bundle), encoding="utf-8")

    result = main(["content", "validate", str(content_path)])

    output = capsys.readouterr()
    assert result == 0
    assert "valid onboarding-v1 sha256:" in output.out
    assert output.err == ""


def test_content_validate_reports_invalid_bundle_without_traceback(tmp_path, capsys) -> None:
    content_path = tmp_path / "bundle.json"
    content_path.write_text("{}", encoding="utf-8")

    result = main(["content", "validate", str(content_path)])

    output = capsys.readouterr()
    assert result == 2
    assert output.out == ""
    assert output.err.startswith("error:")


def test_sessions_cleanup_requires_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    result = main(["sessions", "cleanup"])

    output = capsys.readouterr()
    assert result == 2
    assert output.out == ""
    assert output.err.startswith("error:")
    assert output.err == "error: Set DATABASE_URL before cleaning up sessions\n"


def test_sessions_cleanup_prints_summary_without_content_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, datetime] = {}

    class FakeTransaction:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *exc_info: object) -> None:
            return None

    class FakeSessionFactory:
        def begin(self) -> FakeTransaction:
            return FakeTransaction()

    def fake_cleanup(session: object, now: datetime) -> CleanupResult:
        captured["now"] = now
        return CleanupResult(runs=1, steps=2, sessions=3)

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:secret@localhost/db")
    monkeypatch.setattr(cli, "make_session_factory", lambda url: FakeSessionFactory())
    monkeypatch.setattr(cli, "cleanup_expired_sessions", fake_cleanup)

    result = main(["sessions", "cleanup"])

    output = capsys.readouterr()
    assert result == 0
    assert output.out == "cleanup completed: runs=1 steps=2 sessions=3\n"
    assert output.err == ""
    assert captured["now"].tzinfo is UTC
