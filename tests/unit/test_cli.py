import json

from english_for_developers.cli import main


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
