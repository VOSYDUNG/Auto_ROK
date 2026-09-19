"""Assess direct one-user Windows host input-isolation evidence.

The command is read-only with respect to the desktop.  It validates an
operator-produced ``windows_host_direct`` trace and never starts a VM, changes
Windows features, activates a window, or sends input.
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

from harness.host_input_isolation import (  # noqa: E402
    HostInputIsolationEvidence,
    HostInputIsolationEvidenceError,
)


def _evidence_path(value: str, label: str) -> Path:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, help="operator-produced direct-host trace JSON")
    parser.add_argument("--output", required=True, help="assessment JSON under workspace/evidence")
    parser.add_argument("--run-id", help="optional exact occurrence run id to bind")
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        trace_path = _evidence_path(args.trace, "trace")
        output = _evidence_path(args.output, "output")
        raw = json.loads(trace_path.read_text(encoding="utf-8"))
        trace = raw.get("evidence") if isinstance(raw, dict) and isinstance(raw.get("evidence"), dict) else raw
        evidence = HostInputIsolationEvidence.from_dict(trace)
        ready, reasons = evidence.assess()
        reasons = list(reasons)
        if args.run_id and evidence.run_id != args.run_id:
            reasons.append("host input-isolation trace run_id does not match the current occurrence")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "ready" if not reasons else "blocked",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "trace_path": str(trace_path),
            "evidence": evidence.to_dict(),
            "assessment": {"ready": not reasons, "reasons": reasons},
            "input_emitted": False,
        }
        _write(output, payload)
        printed = dict(payload)
        printed["evidence_path"] = str(output)
        print(json.dumps(printed, ensure_ascii=False))
        return 0 if not reasons else 3
    except (OSError, json.JSONDecodeError, ValueError, HostInputIsolationEvidenceError) as exc:
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
