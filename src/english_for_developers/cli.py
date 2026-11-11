"""Developer commands for validating and publishing onboarding content."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.schema import ContentBundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.database import make_session_factory


def _load_bundle(path: Path) -> ContentBundle:
    raw_content = json.loads(path.read_text(encoding="utf-8"))
    return validate_bundle(raw_content)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m english_for_developers.cli")
    groups = parser.add_subparsers(dest="group", required=True)
    content = groups.add_parser("content", help="manage onboarding content")
    commands = content.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a content JSON file")
    validate.add_argument("path", type=Path)

    publish = commands.add_parser("import", help="store and optionally activate a bundle")
    publish.add_argument("path", type=Path)
    publish.add_argument("--activate", action="store_true")
    publish.add_argument("--threshold-percent", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        bundle = _load_bundle(args.path)
        if args.command == "validate":
            print(f"valid {bundle.bundle_version} sha256:{bundle.content_hash}")
            return 0

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("Set DATABASE_URL before importing content")
        session_factory = make_session_factory(database_url)
        with session_factory.begin() as session:
            result = import_bundle(
                session,
                bundle,
                activate=args.activate,
                threshold_percent=args.threshold_percent,
            )
        action = "stored" if result.inserted else "unchanged"
        publication = " and activated" if result.activated else ""
        print(f"{action} {result.version}{publication}")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("error: database operation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
