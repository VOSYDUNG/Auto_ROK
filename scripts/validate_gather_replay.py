"""Validate durable one-character GATHER_RESOURCE live replay evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_replay_evidence import (  # noqa: E402
    load_gather_replay_records,
    validate_gather_replay,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        help="run evidence directory or one evidence JSON file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_gather_replay_records(args.path)
        report = validate_gather_replay(records)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "FAIL", "errors": [f"{type(exc).__name__}: {exc}"]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
