"""Assess a historical Windows guest/input-isolation trace.

This legacy command is not part of the direct one-machine product path. It
validates archived evidence only; it does not create a guest trace, start a VM,
or send any keyboard/mouse input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.guest_isolation import GuestIsolationEvidence, GuestIsolationEvidenceError  # noqa: E402


def _repo_evidence_path(value: str, label: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "evidence").resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"{label} must be a file under workspace/evidence")
    return path


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, help="operator-produced guest trace JSON")
    parser.add_argument("--output", required=True, help="assessment JSON under workspace/evidence")
    parser.add_argument("--minimum-duration-seconds", type=float, default=1800.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: Path | None = None
    try:
        trace = _repo_evidence_path(args.trace, "trace")
        output = _repo_evidence_path(args.output, "output")
        raw = json.loads(trace.read_text(encoding="utf-8"))
        evidence = GuestIsolationEvidence.from_dict(raw)
        assessment = evidence.assess(minimum_duration_seconds=args.minimum_duration_seconds)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "ready" if assessment.ready else "blocked",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "trace_path": str(trace),
            "evidence": evidence.to_dict(),
            "assessment": {"ready": assessment.ready, "reasons": list(assessment.reasons)},
            "input_emitted": False,
        }
        _write(output, payload)
        printed = dict(payload)
        printed["evidence_path"] = str(output)
        print(json.dumps(printed, ensure_ascii=False))
        return 0 if assessment.ready else 3
    except (OSError, json.JSONDecodeError, ValueError, GuestIsolationEvidenceError) as exc:
        payload = {
            "schema_version": 1,
            "status": "invalid",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }
        if output is not None:
            _write(output, payload)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
