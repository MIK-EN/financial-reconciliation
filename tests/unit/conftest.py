import json
from pathlib import Path

import pytest

from english_for_developers.content.validation import validate_bundle

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


@pytest.fixture
def raw_bundle():
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def bundle(raw_bundle):
    return validate_bundle(raw_bundle)
