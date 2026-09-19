"""Run bounded cancel/resume/recovery checks without touching ROK or host input."""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.mission_ledger import LedgerError, atomic_write, tick, validate_plan  # noqa: E402

NOW = datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)


def _plan(mission_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mission_id": mission_id,
        "timezone": "+07:00",
        "due_local": "08:00",
        "max_attempts": 2,
        "retry_backoff_seconds": [60, 300],
        "steps": [{
            "id": "bounded-step",
            "target_id": "CLAIM",
            "proposal": {"kind": "tap_target"},
            "preconditions": ["scene_ready"],
            "postconditions": ["claimed"],
        }],
    }


def _scene(frame: str, digest: str, *, target: bool = True) -> dict[str, Any]:
    return {
        "status": "READY",
        "scene": {
            "frame_id": frame,
            "targets": [{"target_id": "CLAIM", "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}}] if target else [],
            "facts": {"image_sha256": digest},
        },
    }


def _run_cancel(index: int) -> dict[str, Any]:
    plan = validate_plan(_plan(f"recovery-cancel-{index:02d}"))
    cancelled = tick(plan, None, None, None, NOW, cancel=True)
    resumed = tick(plan, _scene("after-cancel", "b" * 64), "after.json", cancelled, NOW)
    return {
        "case": index,
        "initial_status": cancelled["status"],
        "resume_status": resumed["status"],
        "events_after_resume": len(resumed["events"]),
        "pending_proposal_after_resume": resumed.get("pending_proposal"),
        "passed": cancelled["status"] == "CANCELLED" and resumed == cancelled,
        "input_emitted": False,
    }


def _run_restart(index: int) -> dict[str, Any]:
    plan = validate_plan(_plan(f"recovery-restart-{index:02d}"))
    before = _scene("before", "a" * 64)
    after = _scene("after", "b" * 64)
    proposed = tick(plan, before, "run/before.json", None, NOW)
    with tempfile.TemporaryDirectory(prefix="autorok-recovery-") as folder:
        path = Path(folder) / "ledger.json"
        atomic_write(path, proposed)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        resumed = tick(plan, before, "run/before.json", loaded, NOW)
    resume_idempotent = resumed == proposed
    evidence = {"run/before.json": before, "run/after.json": after}
    pending = proposed["pending_proposal"]
    receipt = {
        "schema_version": 1,
        "mission_id": proposed["mission_id"],
        "occurrence_id": proposed["occurrence_id"],
        "step_id": pending["step_id"],
        "outcome": "verified",
        "before_frame": pending["observation"],
        "after_frame": {"scene_path": "run/after.json", "frame_id": "after", "image_sha256": "b" * 64},
        "verified_at": NOW.isoformat(),
    }
    verified = tick(plan, None, None, resumed, NOW, receipt=receipt, receipt_evidence=evidence)
    restarted_verified = tick(plan, None, None, verified, NOW, receipt_evidence=evidence)
    tampered_blocked = False
    try:
        tick(
            plan,
            None,
            None,
            verified,
            NOW,
            receipt_evidence={"run/before.json": before, "run/after.json": _scene("tampered", "c" * 64)},
        )
    except LedgerError:
        tampered_blocked = True
    return {
        "case": index,
        "proposed_status": proposed["status"],
        "resume_idempotent": resume_idempotent,
        "verified_status": verified["status"],
        "verified_restart_idempotent": restarted_verified == verified,
        "tampered_after_frame_blocked": tampered_blocked,
        "events": len(verified["events"]),
        "passed": (
            proposed["status"] == "PROPOSED"
            and resume_idempotent
            and verified["status"] == "VERIFIED"
            and restarted_verified == verified
            and tampered_blocked
        ),
        "input_emitted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-id", default="recovery-matrix-20260918-01")
    parser.add_argument("--cancel-count", type=int, default=10)
    parser.add_argument("--restart-count", type=int, default=10)
    parser.add_argument("--evidence-root", default=str(ROOT / "workspace" / "evidence" / "recovery"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.cancel_count <= 100 or not 1 <= args.restart_count <= 100:
        raise SystemExit("case counts must be within 1..100")
    cancel_cases = [_run_cancel(index) for index in range(1, args.cancel_count + 1)]
    restart_cases = [_run_restart(index) for index in range(1, args.restart_count + 1)]
    all_cases = cancel_cases + restart_cases
    report = {
        "schema_version": 1,
        "report_id": args.report_id,
        "status": "pass" if all(item["passed"] for item in all_cases) else "fail",
        "measurement_class": "offline_ledger_contract",
        "acceptance": "contract_only_no_live_input",
        "cancel": {"requested": len(cancel_cases), "passed": sum(item["passed"] for item in cancel_cases), "cases": cancel_cases},
        "restart": {"requested": len(restart_cases), "passed": sum(item["passed"] for item in restart_cases), "cases": restart_cases},
        "input_emitted_any": any(item["input_emitted"] for item in all_cases),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    root = Path(args.evidence_root).resolve()
    if not root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
        raise SystemExit("evidence-root must stay under workspace/evidence")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{args.report_id}.json"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    output = dict(report)
    output["evidence_path"] = str(path)
    print(json.dumps(output, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
