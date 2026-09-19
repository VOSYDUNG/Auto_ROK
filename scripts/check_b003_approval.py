"""Read-only check that a troop-selection approval binds the current occurrence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.mission_runtime import MissionContext  # noqa: E402
from harness.troop_policy import TroopSelectionApproval  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--mission-id", default="GATHER_RESOURCE")
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output).resolve()
    if not output.is_relative_to((ROOT / "workspace" / "evidence" / "gather").resolve()):
        raise SystemExit("output must stay under workspace/evidence/gather")
    context = MissionContext(args.mission_id, args.task_id, args.run_id)
    approval = TroopSelectionApproval.load(Path(args.approval).resolve())
    summary = approval.to_summary(context, args.character_id)
    bound = bool(summary.get("bound_to_occurrence"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "approved_for_occurrence" if bound else "blocked_occurrence_mismatch",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "current_occurrence": {
            "mission_id": context.mission_id,
            "task_id": context.task_id,
            "run_id": context.run_id,
            "character_id": args.character_id,
        },
        "approval": summary,
        "input_emitted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    printed = dict(payload)
    printed["evidence_path"] = str(output)
    print(json.dumps(printed, ensure_ascii=False))
    return 0 if bound else 3


if __name__ == "__main__":
    raise SystemExit(main())
