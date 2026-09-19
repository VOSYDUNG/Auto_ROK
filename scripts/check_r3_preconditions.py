"""Check one-character GATHER prerequisites without touching the game.

The preflight is intentionally read-only.  It does not capture, arm input,
create an approval, or infer a troop selection.  It reports whether the exact
run/character has direct-host input-isolation evidence and B003 approval needed
before a live R3 attempt.
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
from harness.main_view_detector import MainViewProfile  # noqa: E402
from harness.mission_runtime import MissionContext  # noqa: E402
from harness.resource_level_control import ResourceLevelProfile  # noqa: E402
from harness.troop_policy import TroopSelectionApproval, TroopSelectionApprovalError  # noqa: E402


def _evidence_path(value: str, label: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "evidence").resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"{label} must stay under workspace/evidence")
    return path


def _load_host_input_isolation(path: str | None, context: MissionContext) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "ready": False,
            "trace_path": None,
            "environment": "windows_host_direct",
            "reasons": ["no direct-host input-isolation evidence supplied"],
        }
    source = _evidence_path(path, "direct-host input-isolation evidence")
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("direct-host input-isolation evidence must be a JSON object")
    trace = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else raw
    evidence = HostInputIsolationEvidence.from_dict(trace)
    _ready, assessment_reasons = evidence.assess()
    reasons = list(assessment_reasons)
    if evidence.run_id != context.run_id:
        reasons.append("direct-host trace run_id does not match the current occurrence")
    return {
        "provided": True,
        "ready": not reasons,
        "trace_path": str(source),
        "evidence_id": evidence.evidence_id,
        "session_id": evidence.session_id,
        "environment": evidence.environment,
        "run_id": evidence.run_id,
        "unexpected_input_events": evidence.unexpected_input_events,
        "reasons": reasons,
    }


def _approval(path: str | None, context: MissionContext, character_id: str) -> dict[str, Any]:
    if path is None:
        return {
            "approved": False,
            "bound_to_occurrence": False,
            "source": "none",
            "reasons": ["no occurrence-bound B003 approval supplied"],
        }
    source = _evidence_path(path, "troop approval")
    approval = TroopSelectionApproval.load(source)
    summary = approval.to_summary(context, character_id)
    if summary.get("bound_to_occurrence") is not True:
        summary["reasons"] = ["approval is not bound to the exact mission/task/run/character"]
    else:
        summary["reasons"] = []
    return summary


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="one-character")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--troop-policy-approval")
    parser.add_argument("--input-isolation-evidence")
    parser.add_argument("--guest-isolation-evidence", help=argparse.SUPPRESS)
    parser.add_argument(
        "--main-view-profile",
        default=str(ROOT / "config" / "main_view_profiles.json"),
    )
    parser.add_argument(
        "--resource-level-profile",
        default=str(ROOT / "config" / "resource_level_profile.json"),
    )
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: Path | None = None
    try:
        output = _evidence_path(args.output, "output")
        context = MissionContext("GATHER_RESOURCE", args.task_id, args.run_id)
        if args.guest_isolation_evidence:
            raise ValueError(
                "GUEST_MODE_OUT_OF_SCOPE: use --input-isolation-evidence for direct one-user host mode"
            )
        host_input_isolation = _load_host_input_isolation(args.input_isolation_evidence, context)
        approval = _approval(args.troop_policy_approval, context, args.character_id)
        main_profile = MainViewProfile.load(Path(args.main_view_profile).resolve())
        resource_profile = ResourceLevelProfile.load(Path(args.resource_level_profile).resolve())
        profiles = {
            "main_view_trained": bool(main_profile.prototypes),
            "resource_level_trained": bool(resource_profile.trained),
        }
        reasons = list(host_input_isolation.get("reasons", [])) + list(approval.get("reasons", []))
        if not profiles["main_view_trained"]:
            reasons.append("main-view profile is not trained")
        if not profiles["resource_level_trained"]:
            reasons.append("resource-level profile is not trained")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "ready" if not reasons else "blocked",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "occurrence": {
                "mission_id": context.mission_id,
                "task_id": context.task_id,
                "run_id": context.run_id,
                "character_id": args.character_id,
            },
            "host_input_isolation": host_input_isolation,
            "b003_approval": approval,
            "profiles": profiles,
            "reasons": reasons,
            "input_emitted": False,
        }
        _write(output, payload)
        printed = dict(payload)
        printed["evidence_path"] = str(output)
        print(json.dumps(printed, ensure_ascii=False))
        return 0 if not reasons else 3
    except (OSError, json.JSONDecodeError, ValueError, HostInputIsolationEvidenceError, TroopSelectionApprovalError) as exc:
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
