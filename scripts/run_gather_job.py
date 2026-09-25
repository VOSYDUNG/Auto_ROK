"""Bounded caller of the canonical one-tick GATHER job CLI.

This driver adds no perception, action selection or input authority. Live job
arming remains disabled until the job-scoped preflight is implemented.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.gather_job_authority import GatherJobAuthority, compiled_gather_catalog  # noqa: E402
from harness.gather_job_coordinator import GatherJobCoordinator  # noqa: E402
from harness.gather_job_startup_attestation import validate_canonical_startup_attestation  # noqa: E402
from harness.gather_job_store import (  # noqa: E402
    GatherJobStoreError, JsonGatherJobStore, load_gather_job_authority,
)
from harness.mission_loader import compile_mission  # noqa: E402
from harness.mission_store import JsonMissionStore  # noqa: E402

GATHER_JOB_STORE_ROOT = ROOT / "workspace" / "checkpoints" / "gather-jobs"
GATHER_CHECKPOINT_ROOT = ROOT / "workspace" / "checkpoints"
GATHER_EVIDENCE_ROOT = ROOT / "workspace" / "evidence" / "gather"


def _valid_closeout(value: object, job_id: str) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 5:
        return False
    seen_runs: set[str] = set()
    for sequence, entry in enumerate(value, 1):
        if not isinstance(entry, Mapping):
            return False
        run_id = entry.get("run_id")
        receipt = entry.get("receipt")
        if (entry.get("job_id") != job_id or entry.get("sequence") != sequence
                or entry.get("before_count") != sequence - 1
                or entry.get("after_count") != sequence
                or entry.get("capacity") != 5
                or not isinstance(run_id, str) or not run_id or run_id in seen_runs
                or not isinstance(receipt, Mapping)
                or receipt.get("action_id") != "MARCH_WITH_CURRENT_SELECTION"
                or receipt.get("target_id") != "TROOP_MARCH"):
            return False
        seen_runs.add(run_id)
    return True


def drive_job(
    tick: Callable[[], tuple[int, Mapping[str, Any]]], *,
    job_id: str, max_ticks: int, max_idle_ticks: int,
    idle_delay_seconds: float, settle_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
    validate_closed: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Advance bounded fresh ticks; never infer success from a receipt alone."""
    if (not isinstance(job_id, str) or not job_id
            or type(max_ticks) is not int or max_ticks < 1
            or type(max_idle_ticks) is not int or max_idle_ticks < 0
            or not isinstance(idle_delay_seconds, (int, float))
            or not math.isfinite(idle_delay_seconds) or idle_delay_seconds < 0
            or not isinstance(settle_seconds, (int, float))
            or not math.isfinite(settle_seconds) or settle_seconds < 0):
        raise ValueError("invalid GATHER job driver bounds")
    last_verified: int | None = None
    active_run: str | None = None
    idle = 0
    history: list[dict[str, Any]] = []

    def outcome(status: str, reason: str, *, closeout: object = None) -> dict[str, Any]:
        return {
            "status": status, "reason": reason, "job_id": job_id,
            "ticks": len(history), "verified_marches": last_verified,
            "history": history, "closeout": closeout,
        }

    for _ in range(max_ticks):
        try:
            code, payload = tick()
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return outcome("failed", f"tick execution failed: {type(exc).__name__}: {exc}")
        if not isinstance(payload, Mapping):
            return outcome("failed", "tick output is not a JSON object")
        status = payload.get("status")
        verified = payload.get("gather_job_verified_marches")
        run_id = payload.get("run_id")
        history.append({
            "status": status, "run_id": run_id, "verified_marches": verified,
            "evidence_path": payload.get("evidence_path"),
        })
        if payload.get("gather_job_id") != job_id:
            return outcome("failed", "tick job identity changed")
        if type(verified) is not int or not 0 <= verified <= 5:
            return outcome("failed", "tick lacks bounded VERIFIED progress")
        if (last_verified is not None and
                (verified < last_verified or verified > last_verified + 1)):
            return outcome("failed", "VERIFIED progress skipped or regressed")
        if payload.get("gather_job_verification_error"):
            return outcome("failed", "job verification failed")
        if payload.get("gather_job_closed_at_five") is True:
            closeout = payload.get("gather_job_closeout")
            if (code == 0 and status == "complete" and verified == 5
                    and _valid_closeout(closeout, job_id)):
                journaled = payload.get("gather_job_journaled_this_tick") is True
                if journaled and (last_verified is None or verified == last_verified + 1):
                    last_verified = verified
                    return outcome("complete", "five VERIFIED marches closed", closeout=closeout)
                if not journaled and validate_closed is not None:
                    try:
                        recovered = validate_closed(payload)
                    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                        recovered = False
                    if recovered:
                        last_verified = verified
                        return outcome("complete", "durable five-march closeout recovered", closeout=closeout)
            return outcome("failed", "5/5 flag lacks a successful journaled tick and validated closeout")
        if verified == 5:
            return outcome("failed", "five VERIFIED marches lack a closeout")
        if code not in {0, 3} or status in {"failed", "blocked", "needs_decision"}:
            return outcome("suspended", f"tick stopped: {status or code}")
        if status not in {"running", "complete", "reobserve", "waiting"}:
            return outcome("failed", "tick returned an unknown state")
        if (active_run is not None and last_verified == verified and
                run_id != active_run):
            return outcome("failed", "occurrence changed before verification")
        if status == "complete" and (
            payload.get("gather_job_journaled_this_tick") is not True
            or last_verified == verified
        ):
            return outcome("failed", "mission COMPLETE did not advance VERIFIED journal")
        advanced = last_verified is None or verified > last_verified
        last_verified = verified
        active_run = (run_id if status != "complete" and isinstance(run_id, str) and run_id
                      else None)
        if status == "complete" or advanced:
            idle = 0
        else:
            idle += 1
            if idle > max_idle_ticks:
                return outcome("suspended", "fresh observation did not advance within idle bound")
        choice = payload.get("choice")
        if isinstance(choice, Mapping) and choice.get("action_id"):
            sleeper(settle_seconds)
        elif status in {"reobserve", "waiting"} or idle:
            sleeper(idle_delay_seconds)
    return outcome("suspended", "GATHER job tick ceiling reached")


def _tick_command(args: argparse.Namespace, startup_attestation_sha256: str) -> list[str]:
    command = [
        sys.executable, str(ROOT / "scripts" / "run_gather_tick.py"),
        "--gather-job", str(args.gather_job),
        "--task-id", args.task_id,
        "--character-id", args.character_id,
        "--resource-type", args.resource_type,
        "--startup-attestation-sha256", startup_attestation_sha256,
    ]
    if args.resource_level is not None:
        command.extend(("--resource-level", str(args.resource_level)))
    return command


_LAUNCH_FIELDS = frozenset({
    "schema_version", "job_artifact", "job_artifact_sha256", "job_id",
    "task_id", "character_id", "catalog_digest", "resource_type", "resource_level",
})


def _launch_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate GATHER launch key: {key}")
        value[key] = item
    return value


def _validated_launch(args: argparse.Namespace) -> tuple[argparse.Namespace, GatherJobAuthority]:
    workspace = (ROOT / "workspace").resolve()
    if args.launch_spec is not None:
        if any((args.gather_job, args.task_id, args.character_id,
                args.resource_type, args.resource_level is not None)):
            raise ValueError("launch spec cannot be mixed with manually entered job parameters")
        spec_path = args.launch_spec.resolve()
        if not spec_path.is_relative_to(workspace):
            raise ValueError("GATHER launch spec must be under workspace")
        spec = json.loads(spec_path.read_text(encoding="utf-8"), object_pairs_hook=_launch_pairs)
        if (not isinstance(spec, dict) or frozenset(spec) != _LAUNCH_FIELDS
                or type(spec["schema_version"]) is not int or spec["schema_version"] != 1
                or any(not isinstance(spec[key], str) or not spec[key].strip()
                       for key in ("job_artifact", "job_artifact_sha256", "job_id",
                                   "task_id", "character_id", "catalog_digest"))
                or spec["resource_type"] not in ("FOOD", "WOOD", "STONE", "GOLD")
                or (spec["resource_level"] is not None
                    and type(spec["resource_level"]) is not int)):
            raise ValueError("invalid GATHER launch spec")
        job_path = Path(spec["job_artifact"]).resolve()
        args = argparse.Namespace(**vars(args))
        args.gather_job = job_path
        args.task_id = spec["task_id"]
        args.character_id = spec["character_id"]
        args.resource_type = spec["resource_type"]
        args.resource_level = spec["resource_level"]
    else:
        if not all((args.gather_job, args.task_id, args.character_id, args.resource_type)):
            raise ValueError("supply --launch-spec or all job and resource parameters")
        spec = None
        job_path = args.gather_job.resolve()
    if not job_path.is_relative_to(workspace):
        raise ValueError("GATHER job artifact must be under workspace")
    raw_bytes = job_path.read_bytes()
    if spec is not None and hashlib.sha256(raw_bytes).hexdigest() != spec["job_artifact_sha256"]:
        raise ValueError("GATHER launch artifact hash changed")
    compiled = compile_mission(
        ROOT / "config" / "mission_flows.yaml", ROOT / "config" / "ui_states.yaml",
        "GATHER_RESOURCE", {"resource_type": args.resource_type,
                            "resource_level": args.resource_level},
    )
    catalog = compiled_gather_catalog(compiled)
    job = load_gather_job_authority(
        job_path, canonical_actions=catalog.actions,
        expected_catalog_digest=catalog.digest,
    )
    if job.task_id != args.task_id or job.character_id != args.character_id:
        raise ValueError("GATHER launch identity differs from authority artifact")
    if spec is not None and any((
        spec["job_id"] != job.job_id,
        spec["task_id"] != job.task_id,
        spec["character_id"] != job.character_id,
        spec["catalog_digest"] != job.catalog_digest,
    )):
        raise ValueError("GATHER launch metadata differs from authority artifact")
    return args, job


def _durably_closed(job: GatherJobAuthority, payload: Mapping[str, Any]) -> bool:
    """Accept an already-closed CLI tick only from the durable journal and closeout."""
    plan = GatherJobCoordinator(
        job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
        JsonMissionStore(GATHER_CHECKPOINT_ROOT),
    ).plan()
    if not plan.closed or plan.closeout is None or list(plan.closeout) != payload.get("gather_job_closeout"):
        return False
    digest = hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()
    expected = GATHER_EVIDENCE_ROOT / "jobs" / f"gather-job-{digest}-closeout.json"
    source = payload.get("gather_job_closeout_path")
    if not isinstance(source, str) or Path(source).resolve() != expected.resolve():
        return False
    record = json.loads(expected.read_text(encoding="utf-8"))
    return record == {
        "schema_version": 1, "job_id": job.job_id, "task_id": job.task_id,
        "character_id": job.character_id, "catalog_digest": job.catalog_digest,
        "verified_marches": job.max_marches, "transitions": list(plan.closeout),
    }


def _subprocess_tick(command: list[str]) -> tuple[int, Mapping[str, Any]]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300)
    for output in (completed.stdout, completed.stderr):
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return completed.returncode, value
    return completed.returncode, {"status": "failed", "error": "tick emitted no JSON result"}


def _write_report(root: Path, result: Mapping[str, Any]) -> Path:
    if not root.resolve().is_relative_to((ROOT / "workspace").resolve()):
        raise ValueError("driver report root must be under workspace")
    job_id = str(result["job_id"])
    directory = root / hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    sequence = result.get("attempt_sequence")
    destination = (directory / f"attempt-{sequence:06d}.result.json"
                   if type(sequence) is int and sequence > 0
                   else directory / f"attempt-{time.time_ns()}-{os.getpid()}.json")
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(result), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def _write_attempt_start(
    root: Path, job: GatherJobAuthority, startup_attestation_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    workspace = (ROOT / "workspace").resolve()
    if not root.resolve().is_relative_to(workspace):
        raise ValueError("driver report root must be under workspace")
    directory = root / hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "first-done-closeout.json").exists():
        raise ValueError("GATHER job already has an immutable FIRST DONE verdict")
    starts = sorted(directory.glob("attempt-*.start.json"))
    sequence = len(starts) + 1
    if any(path.name != f"attempt-{index:06d}.start.json"
           for index, path in enumerate(starts, 1)):
        raise ValueError("GATHER attempt-start chain is not contiguous")
    previous_start = starts[-1] if starts else None
    previous_result = directory / f"attempt-{sequence - 1:06d}.result.json" if starts else None
    if previous_start is not None:
        predecessor = json.loads(previous_start.read_text(encoding="utf-8"),
                                 object_pairs_hook=_launch_pairs)
        if predecessor.get("startup_attestation_sha256") != startup_attestation_sha256:
            raise ValueError("GATHER startup attestation differs across attempts")
    record: dict[str, Any] = {
        "schema_version": 1, "kind": "attempt_start", "job_id": job.job_id,
        "task_id": job.task_id, "character_id": job.character_id,
        "catalog_digest": job.catalog_digest, "attempt_sequence": sequence,
        "startup_attestation_sha256": startup_attestation_sha256,
        "initial_verified": JsonGatherJobStore(GATHER_JOB_STORE_ROOT).progress(job).verified_marches,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "previous_start_sha256": (hashlib.sha256(previous_start.read_bytes()).hexdigest()
                                  if previous_start else None),
        "previous_result_sha256": (hashlib.sha256(previous_result.read_bytes()).hexdigest()
                                   if previous_result is not None and previous_result.is_file()
                                   else None),
    }
    destination = directory / f"attempt-{sequence:06d}.start.json"
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination, record


def _unverdict_terminal_result(root: Path, job: GatherJobAuthority) -> tuple[Path, dict[str, Any]] | None:
    """Find a completed report left behind by a crash before verdict creation."""
    if not root.resolve().is_relative_to((ROOT / "workspace").resolve()):
        raise ValueError("driver report root must be under workspace")
    directory = root / hashlib.sha256(job.job_id.encode("utf-8")).hexdigest()[:20]
    if (directory / "first-done-closeout.json").exists():
        return None
    starts = sorted(directory.glob("attempt-*.start.json"))
    if not starts:
        return None
    latest = directory / f"attempt-{len(starts):06d}.result.json"
    if not latest.exists():
        return None
    result = json.loads(latest.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("GATHER terminal result is not an object")
    return (latest, result) if result.get("status") == "complete" else None


def _audit_closeout(job: GatherJobAuthority, result: Mapping[str, Any], report: Path) -> tuple[str, Path]:
    from scripts.audit_first_done_job import audit_first_done_job, write_verdict

    verdict = audit_first_done_job(
        job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
        JsonMissionStore(GATHER_CHECKPOINT_ROOT), result,
        GATHER_EVIDENCE_ROOT, attempt_root=report.parent,
    )
    destination = write_verdict(
        report.parent / "first-done-closeout.json", ROOT / "workspace", verdict,
    )
    return verdict["status"], destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-spec", type=Path, help="startup launch JSON issued with the job")
    parser.add_argument("--gather-job", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--character-id")
    parser.add_argument("--resource-type", choices=("FOOD", "WOOD", "STONE", "GOLD"))
    parser.add_argument("--resource-level", type=int)
    parser.add_argument("--max-ticks", type=int, default=80)
    parser.add_argument("--max-idle-ticks", type=int, default=3)
    parser.add_argument("--idle-delay-seconds", type=float, default=1.2)
    parser.add_argument("--settle-seconds", type=float, default=1.2)
    parser.add_argument("--report-root", type=Path,
                        default=ROOT / "workspace" / "evidence" / "gather" / "job-drives")
    parser.add_argument("--arm-live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.arm_live:
            raise ValueError("GATHER job live arm is blocked pending job-scoped preflight")
        args, job = _validated_launch(args)
        startup_attestation_sha256 = validate_canonical_startup_attestation(
            args.gather_job, job.job_id,
            resource_type=args.resource_type, resource_level=args.resource_level,
            workspace_root=ROOT / "workspace", ledger_root=GATHER_JOB_STORE_ROOT,
            mission_flows=ROOT / "config" / "mission_flows.yaml",
            ui_states=ROOT / "config" / "ui_states.yaml",
        )
        prior_terminal = _unverdict_terminal_result(args.report_root, job)
        if prior_terminal is not None:
            report, result = prior_terminal
            sequence = result.get("attempt_sequence")
            if type(sequence) is not int or sequence < 1:
                raise ValueError("terminal result has no valid attempt sequence")
            start_path = report.with_name(f"attempt-{sequence:06d}.start.json")
            start = json.loads(start_path.read_text(encoding="utf-8"),
                               object_pairs_hook=_launch_pairs)
            if start.get("startup_attestation_sha256") != startup_attestation_sha256:
                raise ValueError("terminal attestation differs from pinned attempt")
            audit_status, verdict_path = _audit_closeout(job, result, report)
            print(json.dumps({**result, "report_path": str(report),
                              "audit_status": audit_status, "verdict_path": str(verdict_path)},
                             ensure_ascii=False))
            return 0 if audit_status == "OFFLINE_REPLAY_PASS" else 4
        start_path, start = _write_attempt_start(
            args.report_root, job, startup_attestation_sha256,
        )
        from scripts.audit_first_done_job import preflight_attempt_chain
        preflight_attempt_chain(
            job, JsonGatherJobStore(GATHER_JOB_STORE_ROOT),
            JsonMissionStore(GATHER_CHECKPOINT_ROOT), start_path.parent,
            GATHER_EVIDENCE_ROOT,
        )
        command = _tick_command(args, startup_attestation_sha256)

        def attested_tick() -> tuple[int, Mapping[str, Any]]:
            validate_canonical_startup_attestation(
                args.gather_job, job.job_id,
                resource_type=args.resource_type, resource_level=args.resource_level,
                workspace_root=ROOT / "workspace", ledger_root=GATHER_JOB_STORE_ROOT,
                mission_flows=ROOT / "config" / "mission_flows.yaml",
                ui_states=ROOT / "config" / "ui_states.yaml",
                expected_sha256=startup_attestation_sha256,
            )
            return _subprocess_tick(command)

        result = drive_job(
            attested_tick, job_id=job.job_id,
            max_ticks=args.max_ticks, max_idle_ticks=args.max_idle_ticks,
            idle_delay_seconds=args.idle_delay_seconds,
            settle_seconds=args.settle_seconds,
            validate_closed=lambda payload: _durably_closed(job, payload),
        )
        result["recorded_at"] = datetime.now(timezone.utc).isoformat()
        result["attempt_sequence"] = start["attempt_sequence"]
        result["initial_verified"] = start["initial_verified"]
        result["start_sha256"] = hashlib.sha256(start_path.read_bytes()).hexdigest()
        report = _write_report(args.report_root, result)
        audit_status = None
        verdict_path = None
        if result["status"] == "complete":
            audit_status, verdict_path = _audit_closeout(job, result, report)
        print(json.dumps({**result, "report_path": str(report),
                          "audit_status": audit_status,
                          "verdict_path": str(verdict_path) if verdict_path else None},
                         ensure_ascii=False))
        if audit_status == "BLOCKED":
            return 4
        return {"complete": 0, "suspended": 3, "failed": 4}[result["status"]]
    except (OSError, ValueError, json.JSONDecodeError, GatherJobStoreError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
