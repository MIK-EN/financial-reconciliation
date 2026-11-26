import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from english_for_developers.cli import main
from english_for_developers.trainer.content import TrainerContent

CONTENT = Path(__file__).parents[2] / "content" / "trainer-v1.json"


@pytest.fixture
def raw():
    return json.loads(CONTENT.read_text())


def test_authored_content_is_complete_and_hash_is_independent_of_json_format(raw):
    content = TrainerContent.model_validate(raw)
    assert len(content.topics) == 4
    assert sum(len(topic.exercises) for topic in content.topics) == 12
    reordered = json.loads(json.dumps(raw, sort_keys=True))
    assert TrainerContent.model_validate(reordered).content_hash == content.content_hash
    raw["topics"][0]["exercises"][0]["options"][0]["explanation"] += " Новый текст."
    assert TrainerContent.model_validate(raw).content_hash != content.content_hash


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda raw: raw.update(schema_version=2),
        lambda raw: raw.update(version="../bad"),
        lambda raw: raw.update(unexpected=True),
        lambda raw: raw["topics"].pop(),
        lambda raw: raw["topics"][0].update(id="other"),
        lambda raw: raw["topics"].__setitem__(1, raw["topics"][0]),
        lambda raw: raw["topics"][0]["exercises"].pop(),
        lambda raw: raw["topics"][0]["exercises"][1].update(id="review-empty-list"),
        lambda raw: raw["topics"][0]["exercises"][0].update(correct_option_id="missing"),
        lambda raw: raw["topics"][0]["exercises"][0].update(level="C2"),
        lambda raw: raw["topics"][0]["exercises"][0]["options"].pop(),
        lambda raw: raw["topics"][0]["exercises"][0]["options"][0].update(id="b"),
        lambda raw: raw["topics"][0]["exercises"][0]["options"][0].update(explanation=" "),
        lambda raw: raw["topics"][0]["exercises"][0]["options"][0].update(
            text=raw["topics"][0]["exercises"][0]["options"][1]["text"]
        ),
    ],
)
def test_rejects_broken_content(raw, corrupt):
    corrupt(raw)
    with pytest.raises(ValidationError):
        TrainerContent.model_validate(raw)


def test_content_does_not_share_mutable_collections_with_input(raw):
    content = TrainerContent.model_validate(raw)
    raw["topics"].clear()
    assert len(content.topics) == 4
    with pytest.raises(ValidationError):
        content.version = "changed"


def test_cli_can_validate_without_database(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["trainer", "validate", str(CONTENT)]) == 0
    assert "valid trainer-v1 sha256:" in capsys.readouterr().out
    assert main(["trainer", "import", str(CONTENT), "--activate"]) == 2
    assert "Set DATABASE_URL" in capsys.readouterr().err


def test_cli_rejects_invalid_content(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": 42}')
    assert main(["trainer", "validate", str(path)]) == 2
    assert "error:" in capsys.readouterr().err
